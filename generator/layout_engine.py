from __future__ import annotations

from .dect_layout import count_dect_handsets_per_base
from .geometry import (
    DEVICE_HEIGHT,
    DEVICE_WIDTH,
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
    _compute_device_row_layout,
    _compute_dual_switch_row_layouts,
    _count_device_slots,
    _device_anchor,
    _is_telephony_equipment,
    _layout_anchor_node,
    _place_equipment_rows,
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


def _provider_needs_red_ont(provider: object) -> bool:
    """Euskaltel y MásMóvil llevan ONT ZTE marcada en rojo en el diagrama."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(provider or "")).encode("ascii", "ignore").decode()
    compact = text.upper().replace(" ", "")
    return "EUSKALTEL" in compact or "MASMOVIL" in compact


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
    if _provider_needs_red_ont(internet.get("proveedor", "")):
        # Euskaltel y MásMóvil: ONT ZTE con las letras en rojo (aviso visual).
        ont_model = "ONT ZTE"
        ont_label = f"<font color='#d00000'>{ont_label}</font>"
    nodes.extend(
        [
            NodeSpec(
                key="ont",
                kind="device",
                label=ont_label,
                model=ont_model,
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
        backup_height = 120
        nodes.append(
            NodeSpec(
                key="backup",
                kind="device",
                label=f"<b>{backup_model}</b><br>BACKUP",
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
        width=DEVICE_WIDTH,
        height=DEVICE_HEIGHT,
        meta={"propiedad": _ownership(switch_eq), "label_above": True},
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
        # ¿El 2º switch cuelga del 1º (cascada) en vez del router?
        cascada = str(switches[1].get("conectar_a", "")).strip().lower() == "switch1"
        canvas_left, canvas_right = _canvas_bounds()
        usable = canvas_right - canvas_left
        switch_tel = _make_switch_node(
            "switch",
            switches[0],
            int(canvas_left + usable * 0.30 - DEVICE_WIDTH / 2),
            switch_y,
        )
        if cascada:
            # switch_datos debajo del switch_tel, colgando de él (cascada vertical).
            switch_datos = _make_switch_node(
                "switch_datos",
                switches[1],
                switch_tel.x,
                switch_y + DEVICE_HEIGHT + ROUTER_SWITCH_GAP,
            )
        else:
            switch_datos = _make_switch_node(
                "switch_datos",
                switches[1],
                int(canvas_left + usable * 0.70 - DEVICE_WIDTH / 2),
                switch_y,
            )
        nodes.extend([switch_tel, switch_datos])
        exit_tel = _anchor_exit_x(router_node, switch_tel)
        edges.append(
            EdgeSpec(
                "router",
                "switch",
                label="ETH3-LAN",
                exit_x=exit_tel,
                exit_y=1.0,
                entry_x=0.5,
                entry_y=0.0,
                waypoints=_router_switch_waypoints(router_node, switch_tel, exit_x=exit_tel, lane_index=0),
                label_offset_x=-24,
                label_offset_y=-32,
            )
        )
        if cascada:
            # El 2º switch cuelga en vertical del 1º.
            edges.append(
                EdgeSpec(
                    "switch",
                    "switch_datos",
                    label="ETH1",
                    exit_x=0.5,
                    exit_y=1.0,
                    entry_x=0.5,
                    entry_y=0.0,
                    label_offset_x=10,
                    label_offset_y=25,
                )
            )
        else:
            exit_datos = _anchor_exit_x(router_node, switch_datos)
            edges.append(
                EdgeSpec(
                    "router",
                    "switch_datos",
                    label="ETH4-LAN",
                    exit_x=exit_datos,
                    exit_y=1.0,
                    entry_x=0.5,
                    entry_y=0.0,
                    waypoints=_router_switch_waypoints(router_node, switch_datos, exit_x=exit_datos, lane_index=1),
                    label_offset_x=24,
                    label_offset_y=-36,
                )
            )
        return True, True

    switch = switches[0]
    switch_node = _make_switch_node(
        "switch",
        switch,
        router_node.x + (router_node.width - DEVICE_WIDTH) // 2,
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


def build_office_layout(data: dict, include_switch: bool) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    internet = data.get("internet", {})
    nodes, edges = _init_office_nodes(data)
    _place_internet_stack(data, internet, nodes, edges)
    _place_backup(data, internet, nodes, edges)
    has_switch, has_dual_switch = _place_switch(data, nodes, edges, include_switch)
    switch_telefonia = _parse_switch_telefonia(data.get("switch_telefonia"), default=True)
    device_equipos = [eq for eq in data.get("equipos", []) if eq.get("tipo") != "switch"]
    row_layout: _DeviceRowLayout | None = None
    row_layouts: dict[str, _DeviceRowLayout] | None = None
    if has_dual_switch:
        row_layouts = _compute_dual_switch_row_layouts(
            nodes,
            device_equipos,
            switch_telefonia=switch_telefonia,
        )
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
    _place_summary_nodes(data, nodes)
    return nodes, edges


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
