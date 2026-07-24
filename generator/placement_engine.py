"""Motor de colocación de equipos en el layout de oficina.

Calcula las filas de dispositivos bajo el ancla (router/switch), coloca cada
equipo y enruta su cable, con la lógica especial de bases y terminales DECT.

Extraído de `layout_engine` para acotar el tamaño del módulo. Las pruebas
golden (`tests/test_layout_golden.py`) congelan la salida de `build_layout`,
de modo que cualquier cambio de comportamiento aquí se detecta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .cable_routing import (
    SWITCH_ANCHOR_KEYS,
    _anchor_exit_x,
    _bus_waypoints,
    _cable_label_offset,
    _device_bus_y,
)
from .dect_layout import (
    _dect_handset_key,
    _dect_registry_key,
    _is_dect_base,
    _resolve_dect_base,
)
from .geometry import (
    DEVICE_HEIGHT,
    DEVICE_ROW_GAP,
    MIN_SLOT_SPACING,
    PAGE_RIGHT,
    anchor_row_limits as _anchor_row_limits,
    canvas_bounds as _canvas_bounds,
    device_row_layout as _device_row_layout,
    dual_switch_zone_limits as _dual_switch_zone_limits,
    max_slots_for_zone as _max_slots_for_zone,
    max_slots_per_row as _max_slots_per_row,
)
from .layout_labels import (
    display_model as _display_model,
    equipment_label as _equipment_label,
    normalized_model as _normalized_model,
    ownership as _ownership,
    safe as _safe,
)
from .layout_types import EdgeSpec, NodeSpec
from .parser import ValidatedEquipment

DECT_HANDSET_OFFSET_Y = 195
DECT_HANDSET_FAN_STEP = 170
DECT_ROW_EXTRA = 110
DECT_ROW_CLEARANCE = 28
TELEPHONY_TYPES = {"telefono", "terminal_dect", "base_dect", "ata"}


_OVERRIDE_PORT_RE = re.compile(r"^(?:(TEL|DAT)-)?ETH(\d+)$", re.IGNORECASE)

_OVERRIDE_PREFIX_ANCHOR = {"TEL": "switch", "DAT": "switch_datos"}


def _override_port(team: dict) -> dict | None:
    """Normaliza el puerto elegido manualmente a un dict o None.

    Acepta:
      * "TEL-ETHn" → {"anchor": "switch", "port": "ETHn"}
      * "DAT-ETHn" → {"anchor": "switch_datos", "port": "ETHn"}
      * "ETHn"     → {"anchor": None, "port": "ETHn"}  (sin prefijo)
      * inválido/vacío → None

    n es entero 1..48. Los prefijos TEL/DAT solo tienen sentido con 2 switches;
    la decisión de honrarlos (anclaje manual) se toma en `_device_anchor`. La
    validación por ancla (router exige n>=3) se aplica en `next_port_labels`.
    """
    override = _safe(team.get("puerto", "")).strip()
    if not override:
        return None
    match = _OVERRIDE_PORT_RE.match(override)
    if not match:
        return None
    n = int(match.group(2))
    if n < 1 or n > 48:
        return None
    prefix = match.group(1)
    anchor = _OVERRIDE_PREFIX_ANCHOR.get(prefix.upper()) if prefix else None
    return {"anchor": anchor, "port": f"ETH{n}"}


def _is_telephony_equipment(team: dict) -> bool:
    tipo = _safe(team.get("tipo", "")).lower()
    if tipo in TELEPHONY_TYPES:
        return True
    normalized = _normalized_model(team)
    if _dect_handset_key(normalized) is not None or _is_dect_base(normalized):
        return True
    return False


def _count_device_slots(equipos: list) -> int:
    return _count_layout_slots(equipos)


def _count_layout_slots(equipos: list) -> int:
    total = 0
    physical_bases: set[str] = set()
    handset_bases: set[str] = set()

    for index, team in enumerate(equipos):
        if team.get("tipo") == "switch":
            continue
        normalized = _normalized_model(team)
        validated = ValidatedEquipment.from_dict(team, index)
        qty = validated.cantidad
        if _is_dect_base(normalized):
            total += qty
            physical_bases.add(_display_model(_safe(team.get("modelo"))).upper())
            continue
        if _dect_handset_key(normalized):
            base_key = _dect_registry_key(team, normalized)
            if base_key in physical_bases or base_key in handset_bases:
                continue
            handset_bases.add(base_key)
            total += 1
            continue
        total += qty
    return total


def _device_anchor(
    team: dict,
    *,
    has_switch: bool,
    has_dual_switch: bool,
    switch_telefonia: bool,
) -> str:
    if not has_switch:
        return "router"
    # Anclaje manual por puerto elegido:
    #   * TEL-/DAT-ETHn  -> switch de telefonía / de datos (solo con 2 switches)
    #   * ETHn (sin prefijo, n>=3) -> ROUTER principal (hAP), aunque haya switches
    # Esto permite colgar un teléfono del router y el resto de un switch.
    override = _override_port(team)
    if override:
        if has_dual_switch and override["anchor"] in SWITCH_ANCHOR_KEYS:
            return override["anchor"]
        if not has_dual_switch and override["anchor"] in SWITCH_ANCHOR_KEYS:
            # Con un solo switch, cualquier prefijo de switch apunta a ese switch.
            return "switch"
        if override["anchor"] is None and int(override["port"][3:]) >= 3:
            # Puerto del router elegido explícitamente (ETH3/4/5...).
            return "router"
    if has_dual_switch:
        return "switch" if _is_telephony_equipment(team) else "switch_datos"
    if switch_telefonia:
        return "switch"
    if _is_telephony_equipment(team):
        return "router"
    return "switch"


def _layout_anchor_node(nodes: list[NodeSpec], *, has_switch: bool, has_dual_switch: bool) -> NodeSpec:
    if has_dual_switch:
        switch_tel = next(node for node in nodes if node.key == "switch")
        switch_datos = next(node for node in nodes if node.key == "switch_datos")
        left = min(switch_tel.x, switch_datos.x)
        right = max(switch_tel.x + switch_tel.width, switch_datos.x + switch_datos.width)
        return NodeSpec(
            key="layout_anchor",
            kind="virtual",
            label="",
            x=left,
            y=switch_tel.y,
            width=right - left,
            height=switch_tel.height,
        )
    layout_anchor_key = "switch" if has_switch else "router"
    return next(node for node in nodes if node.key == layout_anchor_key)


@dataclass
class _DeviceRowLayout:
    anchor_node: NodeSpec
    total_slots: int
    max_per_row: int
    equipo_y: int
    row_step: int
    constrain_to_anchor: bool = False
    zone_left: int | None = None
    zone_right: int | None = None
    force_horizontal: bool = False


def _compute_anchor_row_layout(
    anchor_node: NodeSpec,
    device_equipos: list,
    *,
    constrain_to_anchor: bool = False,
    zone_left: int | None = None,
    zone_right: int | None = None,
    force_horizontal: bool = False,
) -> _DeviceRowLayout:
    total_slots = _count_device_slots(device_equipos)
    has_dect_handsets = any(_dect_handset_key(_normalized_model(team)) for team in device_equipos)
    equipo_y = anchor_node.y + anchor_node.height + DEVICE_ROW_GAP
    if zone_left is not None and zone_right is not None:
        max_per_row, _ = _max_slots_for_zone(
            total_slots,
            zone_left,
            zone_right,
            force_horizontal=force_horizontal,
        ) if total_slots else (1, 0)
    elif constrain_to_anchor:
        left, right = _anchor_row_limits(anchor_node)
        max_per_row, _ = _max_slots_for_zone(
            total_slots,
            left,
            right,
            force_horizontal=force_horizontal,
        ) if total_slots else (1, 0)
    elif force_horizontal and total_slots:
        max_per_row = total_slots
    else:
        max_per_row, _ = _max_slots_per_row(total_slots) if total_slots else (1, MIN_SLOT_SPACING)
    # Hueco vertical entre filas amplio: la etiqueta de un teléfono puede tener
    # hasta 6 líneas (puerto + modelo + EXT + SN + MAC + IP), ~120px. Con 125 no
    # se solapa con la fila de abajo.
    row_step = DEVICE_HEIGHT + (DECT_ROW_EXTRA if has_dect_handsets else 150)
    if has_dect_handsets:
        handset_band = DECT_HANDSET_OFFSET_Y + DEVICE_HEIGHT + DECT_ROW_CLEARANCE
        row_step = max(row_step, handset_band)
    return _DeviceRowLayout(
        anchor_node=anchor_node,
        total_slots=total_slots,
        max_per_row=max_per_row,
        equipo_y=equipo_y,
        row_step=row_step,
        constrain_to_anchor=constrain_to_anchor,
        zone_left=zone_left,
        zone_right=zone_right,
        force_horizontal=force_horizontal,
    )


def _compute_device_row_layout(
    nodes: list[NodeSpec],
    device_equipos: list,
    *,
    has_switch: bool,
    has_dual_switch: bool,
) -> _DeviceRowLayout:
    anchor_node = _layout_anchor_node(nodes, has_switch=has_switch, has_dual_switch=has_dual_switch)
    total_slots = _count_device_slots(device_equipos)
    telephony_only = bool(device_equipos) and all(_is_telephony_equipment(team) for team in device_equipos)
    force_horizontal = False
    zone_left: int | None = None
    zone_right: int | None = None
    if telephony_only and not has_dual_switch and total_slots > 1:
        canvas_left, _ = _canvas_bounds()
        # Las filas de teléfonos quedan muy por debajo de la tabla resumen
        # (equipo_y >= 445), así que se REPARTEN A LO ANCHO de toda la página
        # (hasta PAGE_RIGHT), no solo hasta la tabla. Así caben más por fila,
        # salen menos filas y se aprovecha el espacio horizontal.
        zone_left, zone_right = canvas_left, PAGE_RIGHT
        fitted, _ = _max_slots_for_zone(
            total_slots,
            zone_left,
            zone_right,
            force_horizontal=True,
        )
        # Si caben todos holgados en una fila, una sola fila; si no,
        # _compute_anchor_row_layout reparte en varias filas a lo ancho.
        force_horizontal = fitted == total_slots
    layout = _compute_anchor_row_layout(
        anchor_node,
        device_equipos,
        force_horizontal=force_horizontal,
        zone_left=zone_left,
        zone_right=zone_right,
    )
    backup_node = next((n for n in nodes if n.key == "backup"), None)
    if backup_node and not has_switch:
        anchor_bottom = max(anchor_node.y + anchor_node.height, backup_node.y + backup_node.height)
        layout = _DeviceRowLayout(
            anchor_node=layout.anchor_node,
            total_slots=layout.total_slots,
            max_per_row=layout.max_per_row,
            equipo_y=anchor_bottom + DEVICE_ROW_GAP,
            row_step=layout.row_step,
            constrain_to_anchor=layout.constrain_to_anchor,
            zone_left=layout.zone_left,
            zone_right=layout.zone_right,
            force_horizontal=layout.force_horizontal,
        )
    return layout


def _compute_dual_switch_row_layouts(
    nodes: list[NodeSpec],
    device_equipos: list,
    *,
    switch_telefonia: bool,
) -> dict[str, _DeviceRowLayout]:
    switch_tel = next(node for node in nodes if node.key == "switch")
    switch_datos = next(node for node in nodes if node.key == "switch_datos")
    telefonia_equipos = []
    datos_equipos = []
    for eq in device_equipos:
        anchor = _device_anchor(
            eq,
            has_switch=True,
            has_dual_switch=True,
            switch_telefonia=switch_telefonia,
        )
        if anchor == "switch":
            telefonia_equipos.append(eq)
        elif anchor == "switch_datos":
            datos_equipos.append(eq)
    tel_left, tel_right = _dual_switch_zone_limits("switch")
    datos_left, datos_right = _dual_switch_zone_limits("switch_datos")
    return {
        "switch": _compute_anchor_row_layout(
            switch_tel,
            telefonia_equipos,
            zone_left=tel_left,
            zone_right=tel_right,
            force_horizontal=True,
        ),
        "switch_datos": _compute_anchor_row_layout(
            switch_datos,
            datos_equipos,
            zone_left=datos_left,
            zone_right=datos_right,
            force_horizontal=True,
        ),
    }


def _router_anchored_equipos(
    device_equipos: list,
    *,
    has_dual_switch: bool,
    switch_telefonia: bool,
) -> list:
    """Equipos que el usuario colgó manualmente del router (puerto ETH>=3 sin
    prefijo de switch) aunque existan switches."""
    return [
        eq
        for eq in device_equipos
        if _device_anchor(
            eq,
            has_switch=True,
            has_dual_switch=has_dual_switch,
            switch_telefonia=switch_telefonia,
        )
        == "router"
    ]


def _compute_single_switch_row_layouts(
    nodes: list[NodeSpec],
    device_equipos: list,
    *,
    switch_telefonia: bool,
) -> dict[str, _DeviceRowLayout]:
    """Filas por ancla con UN switch cuando además hay equipos colgados del
    router (mezcla router+switch). El switch ocupa el ancho completo."""
    switch_node = next(node for node in nodes if node.key == "switch")
    switch_equipos = [
        eq
        for eq in device_equipos
        if _device_anchor(
            eq,
            has_switch=True,
            has_dual_switch=False,
            switch_telefonia=switch_telefonia,
        )
        == "switch"
    ]
    canvas_left, canvas_right = _canvas_bounds()
    return {
        "switch": _compute_anchor_row_layout(
            switch_node,
            switch_equipos,
            zone_left=canvas_left,
            zone_right=canvas_right,
            force_horizontal=True,
        )
    }


def _append_router_row_layout(
    layouts: dict[str, _DeviceRowLayout],
    nodes: list[NodeSpec],
    router_equipos: list,
) -> None:
    """Añade la fila 'router' por DEBAJO de las filas de switch, a ancho
    completo, para los dispositivos colgados manualmente del router (hAP)."""
    if not router_equipos:
        return
    router_node = next(node for node in nodes if node.key == "router")
    bottoms = []
    for lay in layouts.values():
        if lay.total_slots > 0:
            rows = -(-lay.total_slots // max(1, lay.max_per_row))  # ceil
            bottoms.append(lay.equipo_y + rows * lay.row_step)
    # Los teléfonos colgados del router también deben quedar POR DEBAJO del icono
    # del switch (que está centrado bajo el router), no a su misma altura. Si el
    # switch no tiene equipos propios (p. ej. «switch de telefonía» desmarcado y
    # todos los teléfonos van al router), sin esto la fila arrancaría a la altura
    # del switch y el teléfono de la columna central se solaparía con él.
    for switch_key in ("switch", "switch_datos"):
        switch_node = next((n for n in nodes if n.key == switch_key), None)
        if switch_node is not None:
            bottoms.append(switch_node.y + switch_node.height)
    canvas_left, canvas_right = _canvas_bounds()
    base = _compute_anchor_row_layout(
        router_node,
        router_equipos,
        zone_left=canvas_left,
        zone_right=canvas_right,
        force_horizontal=True,
    )
    equipo_y = (max(bottoms) + DEVICE_ROW_GAP) if bottoms else base.equipo_y
    layouts["router"] = _DeviceRowLayout(
        anchor_node=base.anchor_node,
        total_slots=base.total_slots,
        max_per_row=base.max_per_row,
        equipo_y=equipo_y,
        row_step=base.row_step,
        constrain_to_anchor=base.constrain_to_anchor,
        zone_left=base.zone_left,
        zone_right=base.zone_right,
        force_horizontal=base.force_horizontal,
    )


@dataclass
class _DevicePlacementState:
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]
    has_switch: bool
    has_dual_switch: bool
    switch_telefonia: bool
    row_layout: _DeviceRowLayout | None = None
    row_layouts: dict[str, _DeviceRowLayout] | None = None
    slot_index: int = 0
    team_index: int = 1
    router_port_index: int = 3
    manual_router_ports: set[int] | None = None
    manual_switch_ports: dict[str, set[int]] | None = None
    switch_port_indices: dict[str, int] | None = None
    slot_indices: dict[str, int] | None = None
    bus_lane_counters: dict[str, int] | None = None
    lower_lane_counters: dict[str, int] | None = None
    dect_base_registry: dict[str, str] | None = None
    ordered_base_keys: list[str] | None = None
    handsets_on_base: dict[str, int] | None = None
    dect_handset_totals: dict[str, int] | None = None
    node_index: dict[str, NodeSpec] | None = None

    def __post_init__(self) -> None:
        if self.manual_router_ports is None:
            self.manual_router_ports = set()
        if self.manual_switch_ports is None:
            self.manual_switch_ports = {"switch": set(), "switch_datos": set()}
        if self.switch_port_indices is None:
            self.switch_port_indices = {"switch": 1, "switch_datos": 1}
        if self.slot_indices is None:
            self.slot_indices = {}
        if self.bus_lane_counters is None:
            self.bus_lane_counters = {}
        if self.lower_lane_counters is None:
            self.lower_lane_counters = {}
        if self.dect_base_registry is None:
            self.dect_base_registry = {}
        if self.ordered_base_keys is None:
            self.ordered_base_keys = []
        if self.handsets_on_base is None:
            self.handsets_on_base = {}
        if self.dect_handset_totals is None:
            self.dect_handset_totals = {}
        if self.node_index is None:
            # Índice key->NodeSpec para lookups O(1) (evita escaneos lineales
            # repetidos sobre `nodes`, que crece con cada equipo colocado).
            self.node_index = {node.key: node for node in self.nodes}
        if self.has_switch:
            self.router_port_index = 5 if self.has_dual_switch else 4

    def _add_node(self, node: NodeSpec) -> None:
        self.nodes.append(node)
        self.node_index[node.key] = node

    def _layout_for(self, anchor_key: str) -> _DeviceRowLayout:
        if self.row_layouts is not None:
            return self.row_layouts[anchor_key]
        assert self.row_layout is not None
        return self.row_layout

    def next_position(self, anchor_key: str) -> tuple[int, int, int]:
        layout = self._layout_for(anchor_key)
        if self.row_layouts is not None:
            slot_index = self.slot_indices.get(anchor_key, 0)
        else:
            slot_index = self.slot_index
        row_num = slot_index // layout.max_per_row
        col = slot_index % layout.max_per_row
        slots_in_row = min(
            layout.max_per_row,
            layout.total_slots - row_num * layout.max_per_row,
        )
        start_x, spacing = _device_row_layout(
            slots_in_row,
            layout.anchor_node,
            layout=layout,
        )
        x = start_x + col * spacing
        y = layout.equipo_y + row_num * layout.row_step
        row_top_y = layout.equipo_y + row_num * layout.row_step
        if self.row_layouts is not None:
            self.slot_indices[anchor_key] = slot_index + 1
        else:
            self.slot_index += 1
        return x, y, row_top_y

    def next_port_labels(self, anchor_key: str, override_port: str | None = None) -> tuple[str, str]:
        if anchor_key in SWITCH_ANCHOR_KEYS:
            if override_port:
                self.manual_switch_ports[anchor_key].add(int(override_port[3:]))
                return override_port, override_port
            while self.switch_port_indices[anchor_key] in self.manual_switch_ports[anchor_key]:
                self.switch_port_indices[anchor_key] += 1
            port = f"ETH{self.switch_port_indices[anchor_key]}"
            self.switch_port_indices[anchor_key] += 1
            return port, port
        # Para el router, ETH1/ETH2 son WAN/ONT: solo se acepta override >= 3.
        if override_port and int(override_port[3:]) >= 3:
            self.manual_router_ports.add(int(override_port[3:]))
            return f"{override_port}-LAN", override_port
        while self.router_port_index in self.manual_router_ports:
            self.router_port_index += 1
        port = f"ETH{self.router_port_index}"
        cable_label = f"{port}-LAN"
        self.router_port_index += 1
        return cable_label, port

    def place_edge(self, anchor_key: str, target_key: str, label: str, row_top_y: int | None = None) -> None:
        anchor = self.node_index[anchor_key]
        target = self.node_index[target_key]
        layout = self._layout_for(anchor_key)
        lane_index = self.bus_lane_counters.get(anchor_key, 0)
        self.bus_lane_counters[anchor_key] = lane_index + 1
        if anchor_key in SWITCH_ANCHOR_KEYS | {"router"}:
            # Cada cable sale de un PUNTO PROPIO del switch/router, repartido a lo
            # ancho de su borde inferior en el orden de los equipos (izq→der). Antes
            # el punto de salida era proporcional a la posición del equipo y se
            # SATURABA en los extremos (0.06/0.94) cuando los equipos quedaban lejos
            # del switch estrecho: varios cables salían del mismo punto y parecía
            # que unas líneas salían de otras. Ahora cada línea arranca del switch.
            total = max(1, layout.total_slots)
            exit_x = (lane_index + 1) / (total + 1)
        else:
            exit_x = 0.5
        # Si el equipo está en una fila POR DEBAJO de la primera, el cable NO puede
        # bajar en vertical desde el switch (cruzaría los equipos de arriba). Gira
        # en una banda JUSTO bajo el switch (encima de la primera fila) y baja por
        # el centro del equipo, que cae en el HUECO entre los equipos de arriba.
        first_row_top = layout.equipo_y
        if target.y > first_row_top + 20:
            j = self.lower_lane_counters.get(anchor_key, 0)
            self.lower_lane_counters[anchor_key] = j + 1
            band_top = anchor.y + anchor.height + 24
            bus_y = min(band_top + j * 18, first_row_top - 28)
        else:
            bus_y = _device_bus_y(anchor, target, row_top_y, lane_index=lane_index)
        waypoints = _bus_waypoints(anchor, target, exit_x=exit_x, bus_y=bus_y)
        label_offset_x, label_offset_y = _cable_label_offset(
            label,
            anchor_key=anchor_key,
            lane_index=lane_index,
            anchor=anchor,
            target=target,
        )
        self.edges.append(
            EdgeSpec(
                anchor_key,
                target_key,
                label=label,
                exit_x=exit_x,
                exit_y=1.0,
                entry_x=0.5,
                entry_y=0.0,
                waypoints=waypoints,
                label_offset_x=label_offset_x,
                label_offset_y=label_offset_y,
            )
        )

    def anchor_for(self, team: dict) -> str:
        return _device_anchor(
            team,
            has_switch=self.has_switch,
            has_dual_switch=self.has_dual_switch,
            switch_telefonia=self.switch_telefonia,
        )

    def register_manual_ports(self, data: dict) -> None:
        """Pre-registra TODOS los puertos manuales (router y por switch).

        Recorre `data['equipos']` una sola vez antes de la auto-asignación para
        que ésta salte siempre cualquier puerto elegido manualmente, sin
        importar el orden en que aparezcan los equipos con y sin override.
        """
        for team in data.get("equipos", []):
            if team.get("tipo") == "switch":
                continue
            override = _override_port(team)
            if not override:
                continue
            port_num = int(override["port"][3:])
            anchor_key = self.anchor_for(team)
            if anchor_key in SWITCH_ANCHOR_KEYS:
                self.manual_switch_ports[anchor_key].add(port_num)
            elif port_num >= 3:
                # ETH1/ETH2 del router son WAN/ONT: se ignoran (auto).
                self.manual_router_ports.add(port_num)

    def handset_total_for_base(self, base_key: str) -> int:
        """Total de handsets que REALMENTE se apilan sobre `base_key`.

        `dect_handset_totals` está indexado por `registry_key`, pero varios
        `registry_key` pueden compartir una misma base (fallback de base única
        en `_place_dect_handset`). Aquí se agregan los totales de todos los
        `registry_key` que resuelven a esta `base_key` para que el centrado del
        abanico use el número correcto de terminales.
        """
        total = 0
        for reg_key, count in self.dect_handset_totals.items():
            resolved = self.dect_base_registry.get(reg_key)
            if resolved is None and len(self.ordered_base_keys) == 1:
                resolved = self.ordered_base_keys[0]
            if resolved == base_key:
                total += count
        return total


def _create_dect_base(state: _DevicePlacementState, team: dict, normalized_model: str) -> str:
    registry_key = _dect_registry_key(team, normalized_model)
    base_model_name = _display_model(_resolve_dect_base(team, normalized_model))
    base_key = f"team_{state.team_index}"
    anchor_key = state.anchor_for(team)
    base_x, base_y, row_top_y = state.next_position(anchor_key)
    _base_override = _override_port(team)
    cable_label, port_label = state.next_port_labels(
        anchor_key,
        override_port=_base_override["port"] if _base_override else None,
    )
    state._add_node(
        NodeSpec(
            key=base_key,
            kind="device",
            label=_equipment_label({"modelo": base_model_name}, port_label=port_label),
            model=base_model_name,
            x=base_x,
            y=base_y,
            width=150,
            height=150,
            meta={"tipo": "base_dect", "dect_role": "base", "propiedad": _ownership(team)},
        )
    )
    # El cable de la base DECT tampoco lleva etiqueta: el puerto (ETHn) ya se ve
    # en la etiqueta de la propia base.
    state.place_edge(anchor_key, base_key, "", row_top_y)
    state.dect_base_registry[registry_key] = base_key
    state.ordered_base_keys.append(base_key)
    state.handsets_on_base[base_key] = 0
    return base_key


def _place_dect_handset(
    state: _DevicePlacementState,
    team: dict,
    *,
    normalized_model: str,
    extension: str,
) -> None:
    registry_key = _dect_registry_key(team, normalized_model)
    base_key = state.dect_base_registry.get(registry_key)
    if not base_key and not _safe(team.get("dect_base", "")).strip() and len(state.ordered_base_keys) == 1:
        base_key = state.ordered_base_keys[0]
    if not base_key:
        base_key = _create_dect_base(state, team, normalized_model)
        state.team_index += 1

    base_node = state.node_index[base_key]
    stack_index = state.handsets_on_base.get(base_key, 0)
    total_on_base = state.handset_total_for_base(base_key) or (stack_index + 1)
    handset_y = base_node.y + DECT_HANDSET_OFFSET_Y
    # Abanico de handsets alrededor de la base. Con muchos handsets el paso fijo
    # (170) sacaba las cajas fuera de la página (x negativo o > PAGE_RIGHT).
    # Estrategia: mantener el paso (para NO solapar los handsets) y DESPLAZAR el
    # abanico lo justo para que quepa; solo se reduce el paso si el abanico es más
    # ancho que el propio lienzo (caso extremo, muchísimos handsets).
    half = (total_on_base - 1) / 2
    step = DECT_HANDSET_FAN_STEP
    dx = 0.0
    if half > 0:
        left_margin, _ = _canvas_bounds()
        lo_bound, hi_bound = left_margin, PAGE_RIGHT - 150  # x-izq del icono (ancho 150)
        if 2 * half * step > (hi_bound - lo_bound):
            step = (hi_bound - lo_bound) / (2 * half)
        left_x = base_node.x - half * step   # icono más a la izquierda
        right_x = base_node.x + half * step  # icono más a la derecha
        if left_x < lo_bound:
            dx = lo_bound - left_x
        elif right_x > hi_bound:
            dx = hi_bound - right_x
    center_offset = (stack_index - half) * step
    handset_x = int(base_node.x + dx + center_offset)
    key = f"team_{state.team_index}"
    handset_label = _equipment_label(team, extension=extension)
    state._add_node(
        NodeSpec(
            key=key,
            kind="device",
            label=handset_label,
            model=team.get("modelo", team.get("tipo", "Equipo")),
            x=handset_x,
            y=handset_y,
            width=150,
            height=150,
            meta={
                "tipo": team.get("tipo"),
                "dect_role": "handset",
                "propiedad": _ownership(team),
                "piso": _safe(team.get("piso", "")).strip(),
            },
        )
    )
    state.edges.append(
        EdgeSpec(
            base_key,
            key,
            label="DECT",
            exit_x=0.5,
            exit_y=1.0,
            entry_x=0.5,
            entry_y=0.0,
        )
    )
    state.handsets_on_base[base_key] = stack_index + 1
    state.team_index += 1


def _expansor_count(team: dict) -> int:
    """Nº de módulos de expansión de un terminal. Acepta int, str numérica o bool."""
    v = team.get("expansor")
    if v in (None, "", False, 0, "0"):
        return 0
    if v is True:
        return 1
    try:
        return max(0, int(str(v).strip() or 0))
    except (TypeError, ValueError):
        return 0


def _place_device_row(
    state: _DevicePlacementState,
    team: dict,
    *,
    extension: str,
    is_dect_base: bool,
) -> None:
    key = f"team_{state.team_index}"
    anchor_key = state.anchor_for(team)
    node_x, node_y, row_top_y = state.next_position(anchor_key)
    _row_override = _override_port(team)
    cable_label, port_label = state.next_port_labels(
        anchor_key,
        override_port=_row_override["port"] if _row_override else None,
    )
    state._add_node(
        NodeSpec(
            key=key,
            kind="device",
            label=_equipment_label(team, extension=extension, port_label=port_label),
            model=team.get("modelo", team.get("tipo", "Equipo")),
            x=node_x,
            y=node_y,
            width=150,
            height=150,
            meta={
                "tipo": team.get("tipo"),
                "dect_role": "base" if is_dect_base else "",
                "propiedad": _ownership(team),
                "piso": _safe(team.get("piso", "")).strip(),
                "expansor": _expansor_count(team),
                "expansor_modelo": _safe(team.get("expansor_modelo", "")).strip(),
            },
        )
    )
    if is_dect_base:
        registry_key = _display_model(_safe(team.get("modelo"))).upper()
        if registry_key and registry_key not in state.dect_base_registry:
            state.dect_base_registry[registry_key] = key
            state.ordered_base_keys.append(key)
        state.handsets_on_base[key] = state.handsets_on_base.get(key, 0)
    # El cable del dispositivo va SIN etiqueta: el puerto (ETHn) ya se ve, claro y
    # sin ambigüedad, en la PRIMERA línea (verde) de la etiqueta del propio
    # teléfono. Ponerlo también sobre el cable amontonaba etiquetas ETH en la zona
    # donde los cables se cruzan y no se sabía de qué cable era cada una.
    state.place_edge(anchor_key, key, "", row_top_y)
    state.team_index += 1


def _place_equipment_rows(
    data: dict,
    state: _DevicePlacementState,
) -> None:
    state.register_manual_ports(data)
    for team_index_in_data, team in enumerate(data.get("equipos", [])):
        if team.get("tipo") == "switch":
            continue
        validated = ValidatedEquipment.from_dict(team, team_index_in_data)
        qty = validated.cantidad
        exts = validated.extensiones
        normalized_model = _normalized_model(team)
        is_dect_base = _is_dect_base(normalized_model)
        is_dect_handset = _dect_handset_key(normalized_model) is not None
        if is_dect_base:
            registry_key = _display_model(_safe(team.get("modelo"))).upper()
            if registry_key in state.dect_base_registry:
                continue
        for idx in range(qty):
            extension = exts[idx] if idx < len(exts) else team.get("extension", "")
            if is_dect_handset:
                _place_dect_handset(state, team, normalized_model=normalized_model, extension=extension)
                continue
            _place_device_row(state, team, extension=extension, is_dect_base=is_dect_base)
