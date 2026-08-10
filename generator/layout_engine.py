from __future__ import annotations

from .dect_layout import count_dect_handsets_per_base
from .geometry import (
    DEVICE_HEIGHT,
    DEVICE_WIDTH,
    PAGE_RIGHT,
    SUMMARY_X,
    canvas_bounds as _canvas_bounds,
)
from .parser import REQUIRED_FIELDS, ValidatedEquipment, validate_input_schema
from .cable_routing import (
    SWITCH_ANCHOR_KEYS,
    _anchor_exit_x,
    _bus_waypoints,
    _device_bus_y,
    _router_switch_waypoints,
)
from .layout_labels import (
    display_model as _display_model,
    internet_metric_label as _internet_metric_label,
    is_4g_monitored as _is_4g_monitored,
    ownership as _ownership,
    router_label as _router_label,
    safe as _safe,
    switch_icon_model as _switch_icon_model,
)
from .layout_types import EdgeSpec, NodeSpec
from .equipment_summary import summarize_equipment
from .placement_engine import (
    _DevicePlacementState,
    _DeviceRowLayout,
    _append_router_row_layout,
    _compute_device_row_layout,
    _compute_dual_switch_row_layouts,
    _compute_single_switch_row_layouts,
    _count_device_slots,
    _device_anchor,
    _is_telephony_equipment,
    _layout_anchor_node,
    _place_equipment_rows,
    _router_anchored_equipos,
)

# Re-exportados para compatibilidad: drawio_writer importa NodeSpec/EdgeSpec/
# SWITCH_ANCHOR_KEYS desde aquí; los tests importan summarize_equipment,
# SUMMARY_X, _canvas_bounds y _anchor_exit_x desde este módulo.
__all__ = [
    "NodeSpec",
    "EdgeSpec",
    "SWITCH_ANCHOR_KEYS",
    "_bus_waypoints",
    "_device_bus_y",
    "summarize_equipment",
    "validate_input_data",
    "build_layout",
    "build_office_layout",
    "build_rack_layout",
    "build_multisite_layout",
]

SUMMARY_WIDTH = 380
SUMMARY_TITLE_Y = 75
SUMMARY_Y = 105
SUMMARY_HEIGHT = 165
ROUTER_BACKUP_GAP = 70
ROUTER_SWITCH_GAP = 90


def _parse_switch_telefonia(value: object, *, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "on", "true", "yes", "si", "sí"}


def _router_lan_ports(model: str) -> int:
    """Bocas LAN útiles del router. En el hAP ac2/ac3, ETH1=WAN y ETH2=ONT/backup,
    así que quedan ETH3, ETH4 y ETH5 = 3 bocas. El CHATEAU tiene alguna más."""
    m = (model or "").lower()
    if "chateau" in m:
        return 4
    return 3


def validate_input_data(data: dict) -> list[str]:
    validate_input_schema(data)
    warnings: list[str] = []
    internet = data.get("internet", {})
    router_model = _display_model(_safe(data.get("router", {}).get("modelo", "")))
    if (
        "BACK UP" in _safe(internet.get("tipo", "")).upper()
        and router_model != "CHATEAU"
        and not internet.get("backup")
    ):
        warnings.append("La conexion Fibra + Backup con hAP ac2/ac3 necesita seleccionar WAP LTE o TELTONIKA para ETH2.")
    for index, team in enumerate(data.get("equipos", [])):
        validated = ValidatedEquipment.from_dict(team, index)
        qty = validated.cantidad
        extensions = validated.extensiones
        if qty > len(extensions) and extensions:
            warnings.append(
                f"El equipo '{team.get('modelo', team.get('tipo', 'Equipo'))}' tiene cantidad {qty} y solo {len(extensions)} extension(es)."
            )
    # ¿Más equipos que bocas LAN del router y SIN switch? -> hace falta un switch.
    equipos = data.get("equipos", [])
    if not _expand_switch_equipment(equipos):
        device_equipos = [team for team in equipos if team.get("tipo") != "switch"]
        slots = _count_device_slots(device_equipos)
        lan_ports = _router_lan_ports(router_model)
        if slots > lan_ports:
            warnings.append(
                f"Hay {slots} equipos para conectar y el router "
                f"{router_model or 'hAP'} solo tiene {lan_ports} bocas LAN "
                f"(ETH3–ETH{lan_ports + 2}). NECESITAS AÑADIR UN SWITCH para "
                "conectarlos todos."
            )
    return warnings


def build_layout(data: dict) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    validate_input_schema(data)
    missing = [field for field in REQUIRED_FIELDS if not data.get(field)]
    if missing:
        raise ValueError(f"Faltan campos obligatorios: {', '.join(missing)}")
    template = data.get("template", "oficina_simple")
    if template == "rack":
        return build_rack_layout(data)
    if template == "multisede":
        return build_multisite_layout(data)
    return build_office_layout(data, include_switch=(template == "con_switch"))


def _init_office_nodes(data: dict) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    nodes: list[NodeSpec] = [
        NodeSpec(
            key="header",
            kind="text",
            label=(
                f"<div style='text-align:start;'><b>{_safe(data['cliente'])}</b> - {_safe(data.get('cif', ''))}</div>"
                f"<div style='text-align:start;'>{_safe(data['sede'])}</div>"
                f"<div style='text-align:start;'>{_safe(data['direccion'])}</div>"
            ),
            x=860,
            y=10,
            width=280,
            height=60,
        ),
        NodeSpec(key="inet", kind="cloud", label="INET", x=50, y=30, width=120, height=80),
    ]
    return nodes, []


def _norm_provider(value: object) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return text.upper().replace(" ", "")


def _provider_needs_red_ont(provider: object) -> bool:
    """Euskaltel y MásMóvil llevan ONT ZTE marcada en rojo en el diagrama."""
    compact = _norm_provider(provider)
    return "EUSKALTEL" in compact or "MASMOVIL" in compact


def _ont_is_provider_owned(ont_model: object, provider: object) -> bool:
    """ONT que es PROPIEDAD del proveedor (p. ej. ADAMO): se dibuja con un icono
    de ONT normal (genérico) pero con el NOMBRE en rojo, porque el equipo es del
    proveedor, no del cliente."""
    return "ADAMO" in _norm_provider(ont_model) or "ADAMO" in _norm_provider(provider)


def _place_internet_stack(
    data: dict,
    internet: dict,
    nodes: list[NodeSpec],
    edges: list[EdgeSpec],
) -> None:
    if _is_4g_monitored(internet):
        nodes.append(
            NodeSpec(
                key="router",
                kind="device",
                label=_router_label(data.get("router", {}), internet),
                model=data.get("router", {}).get("modelo", "Router"),
                x=240,
                y=120,
                width=150,
                height=150,
                meta={"piso": _safe(data.get("router", {}).get("piso", "")).strip()},
            )
        )
        edges.append(EdgeSpec("inet", "router", exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5))
        return
    ont_label = (
        f"<b>ONT</b><br><b>{_safe(internet.get('tipo', ''))} "
        f"{_internet_metric_label(internet)}</b>"
        f"<br>{_safe(internet.get('proveedor', ''))}"
    )
    ont_model = data.get("ont", {}).get("modelo", "ONT")
    proveedor = internet.get("proveedor", "")
    ont_icon: str | None = None  # por defecto el icono se resuelve del modelo
    if _provider_needs_red_ont(proveedor):
        # Euskaltel y MásMóvil: ONT ZTE con las letras en rojo (aviso visual).
        ont_model = "ONT ZTE"
        ont_label = f"<font color='#d00000'>{ont_label}</font>"
    elif _ont_is_provider_owned(ont_model, proveedor):
        # ADAMO: la ONT no tiene icono propio (salía como caja vacía). Usamos el
        # icono de ONT normal (genérico) y ponemos el NOMBRE en rojo porque el
        # equipo es del proveedor, no del cliente.
        ont_icon = "ONT"
        ont_label = f"<font color='#d00000'>{ont_label}</font>"
    nodes.extend(
        [
            NodeSpec(
                key="ont",
                kind="device",
                label=ont_label,
                model=ont_model,
                icon_model=ont_icon,
                x=240,
                y=120,
                width=150,
                height=150,
            ),
            NodeSpec(
                key="router",
                kind="device",
                label=_router_label(data.get("router", {})),
                model=data.get("router", {}).get("modelo", "Router"),
                x=470,
                y=120,
                width=150,
                height=150,
                meta={"piso": _safe(data.get("router", {}).get("piso", "")).strip()},
            ),
        ]
    )
    edges.extend(
        [
            EdgeSpec("inet", "ont", exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5),
            EdgeSpec(
                "ont",
                "router",
                label="ETH1-WAN",
                exit_x=1.0,
                exit_y=0.5,
                entry_x=0.0,
                entry_y=0.5,
                label_offset_x=0,
                label_offset_y=-24,
            ),
        ]
    )


def _place_backup(
    data: dict,
    internet: dict,
    nodes: list[NodeSpec],
    edges: list[EdgeSpec],
) -> None:
    router_model = _display_model(_safe(data.get("router", {}).get("modelo", "")))
    backup_model = _safe(internet.get("backup", ""))
    has_backup_service = "BACK UP" in _safe(internet.get("tipo", "")).upper()
    if has_backup_service and router_model == "CHATEAU":
        router_node = next(node for node in nodes if node.key == "router")
        router_node.label += "<br>BACKUP 4G INTEGRADO"
    elif has_backup_service and backup_model:
        router_node = next(node for node in nodes if node.key == "router")
        backup_mac = _safe(internet.get("backup_mac", "")).strip()
        backup_label = f"<b>{backup_model}</b><br>BACKUP"
        if backup_mac:
            backup_label += f"<br>MAC {backup_mac}"
        backup_height = 140 if backup_mac else 120
        nodes.append(
            NodeSpec(
                key="backup",
                kind="device",
                label=backup_label,
                model=backup_model,
                x=router_node.x + router_node.width + ROUTER_BACKUP_GAP,
                y=router_node.y + max(0, (router_node.height - backup_height) // 2),
                width=150,
                height=backup_height,
                meta={"propiedad": "propio"},
            )
        )
        edges.append(
            EdgeSpec(
                "router",
                "backup",
                label="ETH2-BACKUP",
                exit_x=1.0,
                exit_y=0.5,
                entry_x=0.0,
                entry_y=0.5,
                label_offset_x=0,
                label_offset_y=-24,
            )
        )


def _expand_switch_equipment(equipos: list) -> list[dict]:
    expanded: list[dict] = []
    for eq in equipos:
        if eq.get("tipo") != "switch":
            continue
        qty = max(1, int(eq.get("cantidad", 1) or 1))
        for _ in range(qty):
            expanded.append(eq)
    return expanded


# Los switches se dibujan en una caja APAISADA (no cuadrada como los teléfonos):
# las fotos de switch son anchas (~2-3:1) y en una caja 150x150 salían como una
# tira fina con mucho hueco. Con esta proporción la foto se ve como un switch real.
SWITCH_WIDTH = 210
SWITCH_HEIGHT = 104


def _make_switch_node(key: str, switch_eq: dict, x: int, y: int) -> NodeSpec:
    model = _safe(switch_eq.get("modelo", "Switch"))
    display_name = _switch_icon_model(model)
    return NodeSpec(
        key=key,
        kind="device",
        label=f"<b>{display_name}</b>",
        model=model,
        x=x,
        y=y,
        width=SWITCH_WIDTH,
        height=SWITCH_HEIGHT,
        meta={"propiedad": _ownership(switch_eq), "label_above": True,
              "piso": _safe(switch_eq.get("piso", "")).strip()},
        icon_model=display_name,
    )


def _place_switch(
    data: dict,
    nodes: list[NodeSpec],
    edges: list[EdgeSpec],
    include_switch: bool,
) -> tuple[bool, bool]:
    switches = _expand_switch_equipment(data.get("equipos", []))
    has_switch = include_switch and bool(switches)
    if not has_switch:
        return False, False
    has_dual_switch = len(switches) >= 2
    router_node = next(node for node in nodes if node.key == "router")
    switch_y = router_node.y + router_node.height + ROUTER_SWITCH_GAP

    if has_dual_switch:
        sw1_eq, sw2_eq = switches[0], switches[1]
        eq_by_key = {"switch": sw1_eq, "switch_datos": sw2_eq}
        c1 = str(sw1_eq.get("conectar_a", "")).strip().lower()  # "switch2" o ""
        c2 = str(sw2_eq.get("conectar_a", "")).strip().lower()  # "switch1" o ""
        canvas_left, canvas_right = _canvas_bounds()
        usable = canvas_right - canvas_left
        center_x = int(canvas_left + usable * 0.30 - SWITCH_WIDTH / 2)

        # ¿Cascada? Un switch cuelga del otro (en cualquier sentido).
        parent_key = child_key = None
        if c2 == "switch1":
            parent_key, child_key = "switch", "switch_datos"       # sw2 cuelga de sw1
        elif c1 == "switch2":
            parent_key, child_key = "switch_datos", "switch"       # sw1 cuelga de sw2

        if parent_key:
            child_eq = eq_by_key[child_key]
            parent_node = _make_switch_node(parent_key, eq_by_key[parent_key], center_x, switch_y)
            child_node = _make_switch_node(
                child_key, child_eq, center_x, switch_y + SWITCH_HEIGHT + ROUTER_SWITCH_GAP
            )
            node_switch = parent_node if parent_key == "switch" else child_node
            node_datos = parent_node if parent_key == "switch_datos" else child_node
            nodes.extend([node_switch, node_datos])
            # Router -> switch PADRE (el que sube al router).
            exit_p = _anchor_exit_x(router_node, parent_node)
            router_port = str(eq_by_key[parent_key].get("conectar_puerto_router", "")).strip().upper() or "ETH3"
            edges.append(
                EdgeSpec(
                    "router", parent_key, label=f"{router_port}-LAN",
                    exit_x=exit_p, exit_y=1.0, entry_x=0.5, entry_y=0.0,
                    waypoints=_router_switch_waypoints(router_node, parent_node, exit_x=exit_p, lane_index=0),
                    label_offset_x=-24, label_offset_y=-32,
                )
            )
            # Switch PADRE -> switch HIJO (cascada vertical), con el puerto elegido.
            casc_port = str(child_eq.get("conectar_puerto", "ETH1")).strip().upper() or "ETH1"
            edges.append(
                EdgeSpec(
                    parent_key, child_key, label=casc_port,
                    exit_x=0.5, exit_y=1.0, entry_x=0.5, entry_y=0.0,
                    label_offset_x=10, label_offset_y=25,
                )
            )
            return True, True

        # Sin cascada: los dos switches cuelgan del router.
        switch_tel = _make_switch_node("switch", sw1_eq, center_x, switch_y)
        switch_datos = _make_switch_node(
            "switch_datos", sw2_eq, int(canvas_left + usable * 0.70 - SWITCH_WIDTH / 2), switch_y
        )
        nodes.extend([switch_tel, switch_datos])
        exit_tel = _anchor_exit_x(router_node, switch_tel)
        edges.append(
            EdgeSpec(
                "router", "switch", label="ETH3-LAN",
                exit_x=exit_tel, exit_y=1.0, entry_x=0.5, entry_y=0.0,
                waypoints=_router_switch_waypoints(router_node, switch_tel, exit_x=exit_tel, lane_index=0),
                label_offset_x=-24, label_offset_y=-32,
            )
        )
        exit_datos = _anchor_exit_x(router_node, switch_datos)
        edges.append(
            EdgeSpec(
                "router", "switch_datos", label="ETH4-LAN",
                exit_x=exit_datos, exit_y=1.0, entry_x=0.5, entry_y=0.0,
                waypoints=_router_switch_waypoints(router_node, switch_datos, exit_x=exit_datos, lane_index=1),
                label_offset_x=24, label_offset_y=-36,
            )
        )
        return True, True

    switch = switches[0]
    switch_node = _make_switch_node(
        "switch",
        switch,
        router_node.x + (router_node.width - SWITCH_WIDTH) // 2,
        switch_y,
    )
    nodes.append(switch_node)
    edges.append(
        EdgeSpec(
            "router",
            "switch",
            label="ETH3-LAN",
            exit_x=0.5,
            exit_y=1.0,
            entry_x=0.5,
            entry_y=0.0,
            waypoints=_router_switch_waypoints(router_node, switch_node),
            label_offset_x=28,
            label_offset_y=25,
        )
    )
    return True, False


def _place_summary_nodes(data: dict, nodes: list[NodeSpec]) -> None:
    nodes.append(
        NodeSpec(
            key="summary_title",
            kind="plain_text",
            label="Resumen Equipos",
            x=SUMMARY_X + 17,
            y=SUMMARY_TITLE_Y,
            width=160,
            height=30,
        )
    )
    nodes.append(
        NodeSpec(
            key="summary",
            kind="table",
            label=summarize_equipment(data),
            x=SUMMARY_X,
            y=SUMMARY_Y,
            width=SUMMARY_WIDTH,
            height=SUMMARY_HEIGHT,
        )
    )


def _ext_ip_sort_key(team: dict):
    """Clave de orden de un equipo: por extensión (numérica) ascendente y luego
    por IP. Los que no tienen extensión (PC, AP, cámara…) van al final."""
    exts = team.get("extensiones")
    if not exts:
        single = team.get("extension")
        exts = [single] if single else []
    ext_num = None
    for e in exts:
        digits = "".join(c for c in str(e or "") if c.isdigit())
        if digits:
            ext_num = int(digits)
            break
    ip = _safe(team.get("ip", ""))
    ip_key = tuple(int(p) for p in ip.split(".")) if ip.count(".") == 3 and all(
        p.isdigit() for p in ip.split(".")
    ) else (9999,)
    return (0 if ext_num is not None else 1, ext_num if ext_num is not None else 10**9, ip_key)


def build_office_layout(data: dict, include_switch: bool) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    internet = data.get("internet", {})
    nodes, edges = _init_office_nodes(data)
    _place_internet_stack(data, internet, nodes, edges)
    _place_backup(data, internet, nodes, edges)
    has_switch, has_dual_switch = _place_switch(data, nodes, edges, include_switch)
    switch_telefonia = _parse_switch_telefonia(data.get("switch_telefonia"), default=True)
    # Ordenar por EXTENSIÓN (y luego IP) de menor a mayor: aunque los puertos ETH
    # queden en Auto, los teléfonos se colocan y se numeran (ETH3, ETH4…) en ese
    # orden. Los switches conservan su orden (define switch1/switch2). Se reordena
    # data["equipos"] para que TANTO el layout COMO la colocación usen ese orden.
    _switches_in_order = [e for e in data.get("equipos", []) if e.get("tipo") == "switch"]
    device_equipos = sorted(
        [e for e in data.get("equipos", []) if e.get("tipo") != "switch"],
        key=_ext_ip_sort_key,
    )
    data["equipos"] = _switches_in_order + device_equipos
    row_layout: _DeviceRowLayout | None = None
    row_layouts: dict[str, _DeviceRowLayout] | None = None
    # ¿Hay equipos colgados manualmente del router aunque existan switches?
    router_equipos = (
        _router_anchored_equipos(
            device_equipos,
            has_dual_switch=has_dual_switch,
            switch_telefonia=switch_telefonia,
        )
        if has_switch
        else []
    )
    if has_dual_switch:
        row_layouts = _compute_dual_switch_row_layouts(
            nodes,
            device_equipos,
            switch_telefonia=switch_telefonia,
        )
        _append_router_row_layout(row_layouts, nodes, router_equipos)
    elif has_switch and router_equipos:
        # Un solo switch + algún equipo colgado del router: filas por ancla.
        row_layouts = _compute_single_switch_row_layouts(
            nodes,
            device_equipos,
            switch_telefonia=switch_telefonia,
        )
        _append_router_row_layout(row_layouts, nodes, router_equipos)
    else:
        row_layout = _compute_device_row_layout(
            nodes,
            device_equipos,
            has_switch=has_switch,
            has_dual_switch=has_dual_switch,
        )
    state = _DevicePlacementState(
        nodes=nodes,
        edges=edges,
        row_layout=row_layout,
        row_layouts=row_layouts,
        has_switch=has_switch,
        has_dual_switch=has_dual_switch,
        switch_telefonia=switch_telefonia,
        dect_handset_totals=count_dect_handsets_per_base(device_equipos),
    )
    _place_equipment_rows(data, state)
    _order_switch_exits_by_target(nodes, edges)
    # Las aristas ya tienen sus waypoints calculados con las posiciones ACTUALES.
    # Las pasadas siguientes mueven nodos en vertical (holgura de internet,
    # separación de pisos, colisiones de iconos) pero NO los waypoints, así que
    # tras ellas los cables quedarían "ratas" (la línea de bus se queda arriba y
    # el dispositivo baja). Guardamos la Y previa para recolocar los waypoints
    # con el desplazamiento real de cada cable al final.
    pre_shift_y = {n.key: n.y for n in nodes}
    # Holgura contra la pila de internet: si la etiqueta del switch superior
    # pisa la etiqueta (a veces 2 líneas) del ONT/router, baja el switch y todo
    # lo de debajo. Se aplica a TODOS los diagramas para que no se solape nada.
    _avoid_internet_stack_overlap(nodes)
    _resolve_label_overlaps(nodes)
    _separate_floors(nodes, edges)
    _reflow_waypoints_after_shift(nodes, edges, pre_shift_y)
    _place_expanders(nodes)
    _reroute_lower_cables_through_gaps(nodes, edges)
    _place_floor_containers(nodes, edges)
    _place_summary_nodes(data, nodes)
    return nodes, edges


def _piso_of(node: NodeSpec) -> str:
    return str((node.meta or {}).get("piso") or "").strip() if node.meta else ""


def _compute_floors(nodes: list[NodeSpec], edges: list[EdgeSpec]) -> dict[str, set[str]]:
    """Agrupa las keys de nodos por piso. Cada nodo con meta['piso'] cuenta;
    un switch/router con piso arrastra sus colgantes SIN piso (los switches
    colgantes no heredan). Devuelve {piso: set(keys)}."""
    targets_by_source: dict[str, list[str]] = {}
    for e in edges:
        targets_by_source.setdefault(e.source, []).append(e.target)
    node_by_key = {n.key: n for n in nodes}
    floors: dict[str, set[str]] = {}
    for n in nodes:
        piso = _piso_of(n)
        if not piso:
            continue
        floors.setdefault(piso, set()).add(n.key)
        es_switch = n.key in {"switch", "switch_datos"} or (n.meta or {}).get("tipo") == "switch"
        if es_switch or n.key == "router":
            for t in targets_by_source.get(n.key, []):
                tn = node_by_key.get(t)
                t_es_switch = (t in {"switch", "switch_datos"} or (tn.meta or {}).get("tipo") == "switch") if tn else False
                if tn is not None and not _piso_of(tn) and not t_es_switch:
                    floors[piso].add(t)
    return floors


def _separate_floors(nodes: list[NodeSpec], edges: list[EdgeSpec]) -> None:
    """Separa los pisos en BANDAS verticales para que sus cuadros no se solapen.
    Apila los pisos por orden numérico, desplazando hacia abajo los que invaden
    la banda del piso anterior. Solo actúa si hay >=2 pisos. No mueve nodos sin piso."""
    floors = _compute_floors(nodes, edges)
    if len(floors) < 2:
        return
    node_by_key = {n.key: n for n in nodes}
    order = sorted(floors.keys(), key=lambda p: (int("".join(c for c in p if c.isdigit()) or "999")))
    # Márgenes para el espacio que ocupan las etiquetas: los dispositivos llevan
    # su texto DEBAJO (hasta ~120px: puerto/EXT/SN/MAC/IP) y los switches ARRIBA
    # (~45px), más el título "Piso N". El GAP entre bandas los tiene en cuenta.
    LABEL_BELOW = 125
    LABEL_ABOVE = 45
    GAP = 70
    cursor = None  # borde inferior ocupado (incluidas etiquetas)
    for piso in order:
        ns = [node_by_key[k] for k in floors[piso] if k in node_by_key]
        if not ns:
            continue
        ymin = min(n.y for n in ns) - LABEL_ABOVE
        ymax = max(n.y + n.height for n in ns) + LABEL_BELOW
        if cursor is None:
            cursor = ymax
            continue
        if ymin < cursor + GAP:
            delta = int(cursor + GAP - ymin)
            for n in ns:
                n.y += delta
            ymax += delta
        cursor = ymax


def _place_expanders(nodes: list[NodeSpec]) -> None:
    """Dibuja los módulos de expansión pegados a la derecha de su teléfono, con un
    "+" entre medias (estilo de los draws de referencia). Un teléfono lleva N
    módulos si su meta['expansor'] >= 1. Solo se dibuja el módulo si CABE en el
    hueco (sin solaparse con otro icono y sin salirse del lienzo); si no cabe se
    omite para no romper el diagrama."""
    EX_W, EX_H, GAP = 88, 118, 12
    RIGHT_LIMIT = PAGE_RIGHT + 140
    icons = [n for n in nodes if n.kind == "device"]

    def _fits(box: tuple[float, float, float, float], placed: list[NodeSpec]) -> bool:
        x0, y0, x1, y1 = box
        if x0 < 40 or x1 > RIGHT_LIMIT:
            return False
        for o in icons:
            b = (o.x, o.y, o.x + o.width, o.y + o.height)
            if x0 < b[2] and b[0] < x1 and y0 < b[3] and b[1] < y1:
                return False
        for e in placed:
            b = (e.x, e.y, e.x + e.width, e.y + e.height)
            if x0 < b[2] and b[0] < x1 and y0 < b[3] and b[1] < y1:
                return False
        return True

    extra: list[NodeSpec] = []
    for n in list(nodes):
        if n.kind != "device":
            continue
        try:
            count = int((n.meta or {}).get("expansor") or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            continue
        modelo = str((n.meta or {}).get("expansor_modelo") or "").strip()
        label = f"<b>{modelo}</b>" if modelo else "<b>Módulo</b><br>expansión"
        piso = (n.meta or {}).get("piso", "")
        propiedad = (n.meta or {}).get("propiedad", "")
        cur_left = n.x + n.width
        for k in range(count):
            ex_x = cur_left + GAP
            ex_y = n.y + (n.height - EX_H) // 2
            box = (ex_x, ex_y, ex_x + EX_W, ex_y + EX_H)
            if not _fits(box, extra):
                # No hay hueco (fila muy densa o última columna): mejor no dibujarlo
                # que solaparlo. El aviso de la oferta ya indica que hay un módulo.
                break
            plus_x = cur_left + (GAP - 18) // 2
            expander = NodeSpec(
                key=f"{n.key}_exp{k}",
                kind="device",
                label=label,
                model="",
                x=ex_x,
                y=ex_y,
                width=EX_W,
                height=EX_H,
                meta={"tipo": "expansor", "piso": piso, "propiedad": propiedad},
            )
            extra.append(expander)
            extra.append(
                NodeSpec(
                    key=f"{n.key}_plus{k}",
                    kind="plain_text",
                    label="<font style='font-size:22px'><b>+</b></font>",
                    model="",
                    x=plus_x,
                    y=n.y + n.height // 2 - 16,
                    width=18,
                    height=32,
                    meta={"piso": piso},
                )
            )
            cur_left = ex_x + EX_W
    nodes.extend(extra)


def _reroute_lower_cables_through_gaps(nodes: list[NodeSpec], edges: list[EdgeSpec]) -> None:
    """Evita que el cable a un teléfono de una fila INFERIOR baje en vertical por
    encima del icono de un teléfono de una fila superior alineado en su columna.
    Si la bajada por el centro del destino cruzaría el icono de otro dispositivo,
    reencamina el cable para que baje por un HUECO libre y entre al destino con un
    pequeño quiebre horizontal justo encima de él. No toca los cables que ya bajan
    limpios."""
    node_by_key = {n.key: n for n in nodes}
    anchors = SWITCH_ANCHOR_KEYS | {"router"}
    # Obstáculos = TODOS los iconos de equipo (incluidos switches, que están en el
    # medio y un cable del router no debe atravesar). Se excluyen por cable los
    # extremos propios (origen y destino).
    dev_icons = [n for n in nodes if n.kind == "device"]
    for e in edges:
        if e.source not in anchors or not e.waypoints:
            continue
        s = node_by_key.get(e.source)
        t = node_by_key.get(e.target)
        if s is None or t is None or t.kind != "device":
            continue
        tc = t.x + t.width // 2
        bus_y = e.waypoints[-1][1]  # altura del último tramo horizontal del cable
        blockers = [
            d
            for d in dev_icons
            if d.key not in (e.source, e.target)
            and d.x < tc < d.x + d.width
            and d.y + d.height > bus_y
            and d.y < t.y
        ]
        if not blockers:
            continue  # la bajada por el centro no cruza nada: se deja como está
        occupied = [
            (d.x - 16, d.x + d.width + 16)
            for d in dev_icons
            if d.key not in (e.source, e.target)
            and d.y + d.height > bus_y + 4
            and d.y < t.y - 4
        ]
        lane = None
        for off in range(6, 1000, 6):
            for cand in (tc - off, tc + off):
                if all(not (lo <= cand <= hi) for lo, hi in occupied):
                    lane = cand
                    break
            if lane is not None:
                break
        if lane is None:
            continue
        exit_abs = int(s.x + e.exit_x * s.width)
        drop_y = t.y - 30
        wp: list[tuple[int, int]] = []
        if abs(exit_abs - lane) > 6:
            wp.append((exit_abs, bus_y))
        wp.append((lane, bus_y))
        wp.append((lane, drop_y))
        wp.append((tc, drop_y))
        e.waypoints = tuple(wp)


def _order_switch_exits_by_target(nodes: list[NodeSpec], edges: list[EdgeSpec]) -> None:
    """Reasigna los puntos de salida de los cables de cada switch/router para que
    salgan en el MISMO orden horizontal que sus equipos destino: el cable del
    equipo más a la izquierda sale por la izquierda del borde inferior del switch,
    el siguiente un poco más a la derecha, etc. Así el abanico de cables se abre
    sin cruzarse entre sí (antes, un equipo de la fila de abajo podía salir por la
    derecha del switch y volver a cruzar todo el abanico hacia la izquierda)."""
    node_by_key = {n.key: n for n in nodes}
    for anchor_key in ("switch", "switch_datos", "router"):
        anchor = node_by_key.get(anchor_key)
        if anchor is None:
            continue
        dev_edges = [
            e
            for e in edges
            if e.source == anchor_key
            and e.waypoints
            and node_by_key.get(e.target) is not None
            and node_by_key[e.target].kind == "device"
        ]
        if len(dev_edges) < 2:
            continue
        # Orden por X del centro del equipo destino.
        dev_edges.sort(key=lambda e: node_by_key[e.target].x + node_by_key[e.target].width / 2)
        n = len(dev_edges)
        for rank, e in enumerate(dev_edges):
            new_exit_x = (rank + 1) / (n + 1)
            bus_y = e.waypoints[-1][1]  # conserva la altura de giro del cable
            e.exit_x = new_exit_x
            e.waypoints = _bus_waypoints(
                anchor, node_by_key[e.target], exit_x=new_exit_x, bus_y=bus_y
            )


def _reflow_waypoints_after_shift(
    nodes: list[NodeSpec], edges: list[EdgeSpec], pre_shift_y: dict[str, int]
) -> None:
    """Recoloca los waypoints de cada cable tras los desplazamientos verticales de
    nodos (holgura de internet, separación de pisos, colisiones de iconos).

    Las pasadas de reacomodo mueven nodos en Y pero dejan los waypoints en su sitio
    original; con desplazamientos grandes (p. ej. bajar una banda de piso ~800px)
    la línea de bus se queda arriba y el cable «sube y baja» (líneas «ratas»). Cada
    cable ancla su línea de bus a un extremo: los de dispositivo la anclan JUSTO
    encima del destino (`target.y − holgura`); los de router→switch y cascada la
    anclan bajo el origen (`source.bottom + holgura`). Detectamos a cuál está más
    cerca la Y del bus (con las posiciones PREVIAS) y desplazamos los waypoints por
    el movimiento real de ese extremo. Los desplazamientos son solo verticales, así
    que las X de los waypoints siguen siendo válidas."""
    node_by_key = {n.key: n for n in nodes}
    for e in edges:
        if not e.waypoints:
            continue
        s = node_by_key.get(e.source)
        t = node_by_key.get(e.target)
        if s is None or t is None:
            continue
        ds = s.y - pre_shift_y.get(e.source, s.y)
        dt = t.y - pre_shift_y.get(e.target, t.y)
        if ds == 0 and dt == 0:
            continue
        bus_y = e.waypoints[-1][1]  # los waypoints comparten la Y de la línea de bus
        src_bottom_old = pre_shift_y.get(e.source, s.y) + s.height
        tgt_top_old = pre_shift_y.get(e.target, t.y)
        delta = dt if abs(bus_y - tgt_top_old) <= abs(bus_y - src_bottom_old) else ds
        if delta:
            e.waypoints = tuple((x, y + delta) for (x, y) in e.waypoints)


def _place_floor_containers(nodes: list[NodeSpec], edges: list[EdgeSpec]) -> None:
    """Dibuja un rectángulo 'Piso N' que engloba los equipos de cada piso.
    Se inserta al principio de `nodes` (z detrás). Sin pisos no hace nada."""
    node_by_key = {n.key: n for n in nodes}
    floors = _compute_floors(nodes, edges)
    if not floors:
        return
    pad = 30
    # El cuadro debe englobar también las etiquetas: los switches llevan su
    # nombre ARRIBA del icono (~45px) y los dispositivos su texto DEBAJO
    # (nombre/EXT/SN/MAC, ~90px). Además dejamos una banda de título arriba para
    # que "Piso N" no se pise con la etiqueta del switch.
    LABEL_ABOVE = 55
    LABEL_BELOW = 125
    TITLE_BAND = 30
    containers: list[NodeSpec] = []
    for piso, keys in floors.items():
        ns = [node_by_key[k] for k in keys if k in node_by_key]
        if not ns:
            continue
        minx = min(m.x for m in ns) - pad
        miny = min(m.y for m in ns) - LABEL_ABOVE - TITLE_BAND
        maxx = max(m.x + m.width for m in ns) + pad
        maxy = max(m.y + m.height for m in ns) + LABEL_BELOW
        # Etiqueta "PLANTA N" (como en los draws de referencia), conservando el
        # recuadro de color que agrupa los equipos de la planta.
        _digits = "".join(ch for ch in piso if ch.isdigit())
        if _digits:
            label = f"PLANTA {_digits}"
        elif piso.lower().startswith("planta"):
            label = piso
        else:
            label = f"PLANTA {piso}" if piso else "PLANTA"
        # Índice de color: por el número de piso si es numérico, si no por orden.
        digits = "".join(ch for ch in piso if ch.isdigit())
        color_idx = (int(digits) - 1) if digits else len(containers)
        containers.append(
            NodeSpec(key=f"floor_{piso}", kind="floor", label=label,
                     x=int(minx), y=int(miny), width=int(maxx - minx), height=int(maxy - miny),
                     meta={"color_idx": color_idx})
        )
    nodes[:0] = containers


_OVERLAP_INFRA_KEYS = {"router", "router2", "ont", "backup", "inet"}


def _label_extent(node: NodeSpec) -> int:
    """Alto (px) que ocupa la etiqueta de un icono, igual que en drawio_writer:
    max(42, nº_líneas*18 + 10)."""
    lines = max(1, (node.label or "").count("<br>") + 1)
    return max(42, lines * 18 + 10)


def _avoid_internet_stack_overlap(nodes: list[NodeSpec]) -> None:
    """Evita que la etiqueta (arriba) del switch superior choque con la etiqueta
    (abajo, a veces 2 líneas: ONT + tipo de internet) de la pila ONT/router/backup
    cuando el switch queda justo debajo. Si se solapan, baja el switch superior y
    TODO lo que hay debajo (switches inferiores, dispositivos) lo justo para
    despegarlos. Reactivo: si ya hay holgura no mueve nada (golden intactos)."""
    infra = [n for n in nodes if n.key in ("ont", "router", "router2", "backup")]
    switches = [n for n in nodes if n.key in SWITCH_ANCHOR_KEYS]
    if not infra or not switches:
        return
    top_switch = min(switches, key=lambda s: s.y)
    sw_label_h = _label_extent(top_switch)
    sw_label_top = top_switch.y - sw_label_h - 10
    sw_x0, sw_x1 = top_switch.x - 12, top_switch.x + top_switch.width + 12
    worst_bottom = None
    for n in infra:
        ix0, ix1 = n.x - 12, n.x + n.width + 12
        if ix0 < sw_x1 and sw_x0 < ix1:  # se solapan en horizontal
            bottom = n.y + n.height + _label_extent(n)
            worst_bottom = bottom if worst_bottom is None else max(worst_bottom, bottom)
    if worst_bottom is None:
        return
    MARGIN = 18
    if sw_label_top < worst_bottom + MARGIN:
        delta = int(worst_bottom + MARGIN - sw_label_top)
        threshold = top_switch.y - sw_label_h - 10
        for n in nodes:
            if n.key in ("ont", "router", "router2", "backup", "inet",
                         "header", "summary", "summary_title"):
                continue
            if n.kind in {"floor", "header", "table", "cloud", "text", "plain_text"}:
                continue
            if n.y >= threshold:  # el switch superior y todo lo de debajo
                n.y += delta


def _icon_bbox(node: NodeSpec) -> tuple[int, int, int, int]:
    """Caja del icono/elemento (sin la etiqueta). La red de seguridad usa iconos
    y no etiquetas a propósito: hay colocaciones que comparten banda de etiqueta
    por diseño (p.ej. handsets DECT bajo su base) y no deben repelerse."""
    return node.x, node.y, node.x + node.width, node.y + node.height


def _resolve_label_overlaps(nodes: list[NodeSpec]) -> None:
    """Red de seguridad para CUALQUIER diagrama: si el icono de un dispositivo se
    solapa con otro elemento, empuja el inferior hacia abajo lo justo para
    despegarlo. Es reactiva y por caja de ICONO: en un layout bien espaciado
    (caso normal y tests golden) los iconos nunca se tocan, así que no mueve nada;
    solo actúa ante colisiones reales de iconos. No toca infraestructura
    (router/ONT/backup/switch), cabeceras, tablas, nube, sedes ni pisos."""
    def movable(n: NodeSpec) -> bool:
        return (
            n.kind == "device"
            and n.key not in SWITCH_ANCHOR_KEYS
            and n.key not in _OVERLAP_INFRA_KEYS
            and not n.key.startswith("site_")
        )

    movers = sorted((n for n in nodes if movable(n)), key=lambda n: (n.y, n.x))
    if not movers:
        return
    # Obstáculos = todo lo demás (posición fija). Los cuadros de piso NO cuentan:
    # están para CONTENER a los dispositivos, no para repelerlos.
    def collide(a, b):
        # Solo consideramos colisión cuando los iconos se solapan Y están
        # prácticamente en la MISMA columna (>50% de solape horizontal): eso es
        # un apilamiento vertical real. El empaquetado horizontal intencionado
        # (p.ej. teléfonos juntos bajo un switch, handsets DECT en abanico) tiene
        # poco solape horizontal y se deja tal cual.
        if not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]):
            return False
        overlap_x = min(a[2], b[2]) - max(a[0], b[0])
        min_w = min(a[2] - a[0], b[2] - b[0]) or 1
        return overlap_x / min_w > 0.5

    boxes = [_icon_bbox(n) for n in nodes if not movable(n) and n.kind != "floor"]
    for n in movers:
        for _ in range(40):  # tope de seguridad
            a = _icon_bbox(n)
            hit = next((b for b in boxes if collide(a, b)), None)
            if hit is None:
                break
            n.y += int(hit[3] - a[1]) + 8  # despegar por debajo del obstáculo
        boxes.append(_icon_bbox(n))


def build_rack_layout(data: dict) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    nodes, edges = build_office_layout(data, include_switch=True)
    router = next(node for node in nodes if node.key == "router")
    switch_nodes = [node for node in nodes if node.key in SWITCH_ANCHOR_KEYS]
    for node in nodes:
        if node.key == "router":
            node.y = 240
        elif node.key in SWITCH_ANCHOR_KEYS:
            if len(switch_nodes) == 1:
                node.x = router.x + (router.width - node.width) // 2
            node.y = router.y + router.height + ROUTER_SWITCH_GAP
        elif node.key == "backup":
            node.x = router.x + router.width + ROUTER_BACKUP_GAP
            node.y = router.y + max(0, (router.height - node.height) // 2)
        elif node.key.startswith("team_"):
            node.y += 80
        elif node.key == "ont":
            node.y = 240
    return nodes, edges


def build_multisite_layout(data: dict) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    nodes = [
        NodeSpec(key="header", kind="text", label=f"<b>{_safe(data['cliente'])}</b><br>{_safe(data['direccion'])}", x=860, y=10, width=280, height=60),
        NodeSpec(key="inet", kind="cloud", label="INET", x=480, y=40, width=140, height=90),
    ]
    edges: list[EdgeSpec] = []
    sites = data.get("sedes") or [{"sede": data["sede"], "direccion": data["direccion"]}]
    for index, site in enumerate(sites, start=1):
        x = 120 + (index - 1) * 320
        nodes.append(NodeSpec(key=f"site_{index}", kind="device", label=f"<b>{_safe(site.get('sede', f'Sede {index}'))}</b><br>{_safe(site.get('direccion', ''))}", model=site.get("router", {}).get("modelo", data.get("router", {}).get("modelo", "Router")), x=x, y=240, width=150, height=150))
        edges.append(EdgeSpec("inet", f"site_{index}", label=f"VPN {index}", exit_x=0.5, exit_y=1.0, entry_x=0.5, entry_y=0.0))
    nodes.append(NodeSpec(key="summary_title", kind="plain_text", label="Resumen Equipos", x=897, y=150, width=120, height=30))
    nodes.append(NodeSpec(key="summary", kind="table", label=summarize_equipment(data), x=765, y=190, width=385, height=170))
    return nodes, edges
