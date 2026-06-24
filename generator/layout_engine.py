from __future__ import annotations

import re
from dataclasses import dataclass
from .aliases import resolve_alias
from .parser import ValidatedEquipment, validate_input_schema


DECT_BASE_MODELS = {"w60b", "w70b", "w80b", "w90b"}
DECT_HANDSET_MODELS = {"w71h", "w72h", "w53", "w53h", "w73h"}
DECT_HANDSET_BASE = {
    "w71h": "W60B",
    "w72h": "W60B",
    "w53": "W80B",
    "w53h": "W80B",
    "w73h": "YEALINK W90DM",
}
SUMMARY_X = 900
SUMMARY_WIDTH = 380
SUMMARY_TITLE_Y = 75
SUMMARY_Y = 105
SUMMARY_HEIGHT = 165
DEVICE_WIDTH = 150
DEVICE_HEIGHT = 150
DECT_HANDSET_OFFSET_Y = 195
DECT_HANDSET_STACK_STEP = 168
SLOT_SPACING = 235
MIN_SLOT_SPACING = 230
MIN_LEFT_MARGIN = 60
DEVICE_ROW_GAP = 175
DECT_ROW_EXTRA = 110
SWITCH_FALLBACK_ICON = "TP-Link 8P"
SWITCH_ANCHOR_KEYS = frozenset({"switch", "switch_datos"})
DUAL_SWITCH_GAP = 90
ROUTER_BACKUP_GAP = 70
ROUTER_SWITCH_GAP = 90
CABLE_CLEARANCE_ABOVE_DEVICE = 40
CABLE_GAP_BELOW_ANCHOR = 40
BUS_LANE_SPACING = 24
ROUTER_SWITCH_LANE_BASE = 18
TELEPHONY_TYPES = {"telefono", "terminal_dect", "base_dect", "ata"}


def _is_telephony_equipment(team: dict) -> bool:
    tipo = _safe(team.get("tipo", "")).lower()
    if tipo in TELEPHONY_TYPES:
        return True
    normalized = _normalized_model(team)
    if _dect_handset_key(normalized) is not None or _is_dect_base(normalized):
        return True
    return False


def _parse_switch_telefonia(value: object, *, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "on", "true", "yes", "si", "sí"}


def _count_device_slots(equipos: list) -> int:
    return _count_layout_slots(equipos)


def _dect_registry_key(team: dict, normalized_model: str) -> str:
    custom = _safe(team.get("dect_base", "")).strip()
    if custom:
        return _display_model(custom).upper()
    return _display_model(_dect_base_model(normalized_model)).upper()


def _max_dect_stack_depth(equipos: list) -> int:
    counts: dict[str, int] = {}
    for index, team in enumerate(equipos):
        if team.get("tipo") == "switch":
            continue
        normalized = _normalized_model(team)
        if not _dect_handset_key(normalized):
            continue
        validated = ValidatedEquipment.from_dict(team, index)
        key = _dect_registry_key(team, normalized)
        counts[key] = counts.get(key, 0) + validated.cantidad
    return max(counts.values(), default=1)


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


def _row_layout(total_slots: int, max_right: int = SUMMARY_X - 20) -> tuple[int, int]:
    available = max_right - MIN_LEFT_MARGIN
    if total_slots <= 0:
        return MIN_LEFT_MARGIN, MIN_SLOT_SPACING
    if total_slots == 1:
        return MIN_LEFT_MARGIN + (available - DEVICE_WIDTH) // 2, MIN_SLOT_SPACING
    spacing = max(MIN_SLOT_SPACING, min(SLOT_SPACING, (available - DEVICE_WIDTH) // (total_slots - 1)))
    row_width = (total_slots - 1) * spacing + DEVICE_WIDTH
    start_x = MIN_LEFT_MARGIN + (available - row_width) // 2
    return start_x, spacing


def _device_row_layout(
    total_slots: int,
    anchor: NodeSpec,
    max_right: int = SUMMARY_X - 20,
    *,
    constrain_to_anchor: bool = False,
) -> tuple[int, int]:
    if constrain_to_anchor:
        left, right = _anchor_row_limits(anchor)
        available = max(DEVICE_WIDTH, right - left)
        if total_slots <= 1:
            return left + (available - DEVICE_WIDTH) // 2, 0
        spacing = max(
            MIN_SLOT_SPACING,
            min(SLOT_SPACING, (available - DEVICE_WIDTH) // (total_slots - 1)),
        )
        row_width = (total_slots - 1) * spacing + DEVICE_WIDTH
        start_x = left + max(0, (available - row_width) // 2)
        return start_x, spacing
    _, spacing = _row_layout(total_slots, max_right)
    row_width = (total_slots - 1) * spacing + DEVICE_WIDTH
    centered_start = anchor.x + (anchor.width - row_width) // 2
    start_x = max(MIN_LEFT_MARGIN, min(centered_start, max_right - row_width))
    return start_x, spacing


def _max_slots_per_row(total_slots: int, *, max_right: int = SUMMARY_X - 20) -> tuple[int, int]:
    for slots_in_row in range(total_slots, 0, -1):
        _, spacing = _row_layout(slots_in_row, max_right)
        row_width = (slots_in_row - 1) * spacing + DEVICE_WIDTH
        if row_width <= max_right - MIN_LEFT_MARGIN:
            return slots_in_row, spacing
    return 1, 0


def _anchor_row_limits(anchor_node: NodeSpec) -> tuple[int, int]:
    left = max(MIN_LEFT_MARGIN, anchor_node.x - 24)
    right = min(SUMMARY_X - 20, anchor_node.x + anchor_node.width + 24)
    return left, right


def _max_slots_for_anchor(total_slots: int, anchor_node: NodeSpec) -> tuple[int, int]:
    left, right = _anchor_row_limits(anchor_node)
    available = max(DEVICE_WIDTH, right - left)
    for slots_in_row in range(total_slots, 0, -1):
        if slots_in_row == 1:
            return 1, 0
        spacing = max(
            MIN_SLOT_SPACING,
            min(SLOT_SPACING, (available - DEVICE_WIDTH) // (slots_in_row - 1)),
        )
        row_width = (slots_in_row - 1) * spacing + DEVICE_WIDTH
        if row_width <= available:
            return slots_in_row, spacing
    return 1, 0


def _anchor_exit_x(anchor: NodeSpec, target: NodeSpec) -> float:
    target_center = target.x + target.width / 2
    ratio = (target_center - anchor.x) / anchor.width
    return max(0.06, min(0.94, ratio))


def _anchor_exit_point(anchor: NodeSpec, exit_x: float) -> tuple[int, int]:
    return int(anchor.x + exit_x * anchor.width), int(anchor.y + anchor.height)


def _target_entry_point(target: NodeSpec) -> tuple[int, int]:
    return int(target.x + target.width / 2), int(target.y)


def _bus_waypoints(
    anchor: NodeSpec,
    target: NodeSpec,
    *,
    exit_x: float,
    bus_y: int,
) -> tuple[tuple[int, int], ...]:
    exit_x_abs, _ = _anchor_exit_point(anchor, exit_x)
    target_center, _ = _target_entry_point(target)
    if abs(exit_x_abs - target_center) <= 6:
        return ((target_center, bus_y),)
    return ((exit_x_abs, bus_y), (target_center, bus_y))


def _cable_label_offset(
    label: str,
    *,
    anchor_key: str,
    lane_index: int = 0,
    anchor: NodeSpec | None = None,
    target: NodeSpec | None = None,
) -> tuple[int, int]:
    if not label:
        return 0, -14
    if anchor_key in SWITCH_ANCHOR_KEYS and label.startswith("ETH") and not label.endswith("-LAN"):
        return lane_index * 10, -36 - lane_index * 4
    if label.endswith("-LAN") and anchor_key == "router":
        offset_x = 10
        if anchor is not None and target is not None:
            offset_x += int((target.x + target.width / 2) - (anchor.x + anchor.width / 2)) // 4
        return offset_x, -32 - lane_index * 4
    offset_x = 10 if label.endswith("-LAN") and anchor_key == "router" else 0
    offset_y = -30 if label.endswith("-LAN") and anchor_key == "router" else -24
    return offset_x, offset_y - lane_index * 2


def _device_bus_y(
    anchor: NodeSpec,
    target: NodeSpec,
    row_top_y: int | None = None,
    *,
    lane_index: int = 0,
) -> int:
    if row_top_y is not None:
        return row_top_y - CABLE_CLEARANCE_ABOVE_DEVICE - lane_index * BUS_LANE_SPACING
    midpoint = (anchor.y + anchor.height + target.y) // 2
    base = max(anchor.y + anchor.height + CABLE_GAP_BELOW_ANCHOR, midpoint)
    return base - lane_index * BUS_LANE_SPACING


def _router_switch_waypoints(
    router: NodeSpec,
    switch: NodeSpec,
    *,
    lane_index: int = 0,
) -> tuple[tuple[int, int], ...] | None:
    router_center = int(router.x + router.width / 2)
    switch_center = int(switch.x + switch.width / 2)
    joint_y = router.y + router.height + ROUTER_SWITCH_LANE_BASE + lane_index * BUS_LANE_SPACING
    if abs(router_center - switch_center) <= 8:
        return ((switch_center, joint_y),)
    return ((router_center, joint_y), (switch_center, joint_y))


@dataclass
class NodeSpec:
    key: str
    kind: str
    label: str
    x: int
    y: int
    width: int
    height: int
    model: str | None = None
    meta: dict | None = None
    icon_model: str | None = None


@dataclass
class EdgeSpec:
    source: str
    target: str
    label: str | None = None
    exit_x: float = 1.0
    exit_y: float = 0.5
    entry_x: float = 0.5
    entry_y: float = 0.5
    waypoints: tuple[tuple[int, int], ...] | None = None
    label_offset_x: int = 0
    label_offset_y: int = -14


def _safe(value: object) -> str:
    return "" if value is None else str(value)


def _normalized_model(team: dict) -> str:
    return _safe(team.get("modelo", team.get("tipo", ""))).strip().lower()


def _display_model(value: str) -> str:
    return resolve_alias(value or "")


def _switch_icon_model(model: str) -> str:
    without_prefix = re.sub(r"^switch\s+", "", _safe(model).strip(), flags=re.IGNORECASE)
    resolved = _display_model(without_prefix)
    return resolved or SWITCH_FALLBACK_ICON


def _router_label(router: dict, internet: dict | None = None) -> str:
    alias = _display_model(_safe(router.get("modelo", "Router")))
    ip_value = _safe(router.get("ip", ""))
    if alias == "CHATEAU":
        label = f"<b>CHATEAU</b><br>LAN {ip_value}" if ip_value else "<b>CHATEAU</b>"
    else:
        label = f"<b>{alias or 'Router'}</b><br>{ip_value}"
    if internet and _is_4g_monitored(internet):
        label += (
            f"<br><b>{_safe(internet.get('tipo', ''))} "
            f"{_internet_metric_label(internet)}</b>"
            f"<br>{_safe(internet.get('proveedor', ''))}"
        )
    return label


def _is_4g_monitored(internet: dict) -> bool:
    return "4G MONITORIZADO" in _safe(internet.get("tipo", "")).upper()


def _equipment_label(team: dict, extension: str = "", port_label: str = "") -> str:
    display_model = _display_model(_safe(team.get("modelo", team.get("tipo", "Equipo"))))
    parts: list[str] = []
    if port_label:
        parts.append(f"<b>{_safe(port_label)}</b>")
    parts.append(f"<b>{display_model}</b>")
    if extension:
        parts.append(f"EXT {_safe(extension)}")
    if team.get("serial_number"):
        parts.append(f"SN {_safe(team.get('serial_number'))}")
    if team.get("mac"):
        parts.append(f"MAC {_safe(team.get('mac'))}")
    if team.get("ip"):
        parts.append(f"IP {_safe(team.get('ip'))}")
    return "<br>".join(parts)


def _dect_handset_key(normalized_model: str) -> str | None:
    for handset in DECT_HANDSET_MODELS:
        if handset in normalized_model:
            return handset
    return None


def _dect_base_model(normalized_model: str) -> str:
    handset_key = _dect_handset_key(normalized_model)
    if handset_key:
        return DECT_HANDSET_BASE.get(handset_key, "W60B")
    return "W60B"


def _resolve_dect_base(team: dict, normalized_model: str) -> str:
    custom = _safe(team.get("dect_base", "")).strip()
    if custom:
        return _display_model(custom)
    return _dect_base_model(normalized_model)


def _is_dect_base(normalized_model: str) -> bool:
    return any(base in normalized_model for base in DECT_BASE_MODELS)


def _ownership(team: dict) -> str:
    return "ajeno" if _safe(team.get("propiedad", "propio")).lower() in {"ajeno", "no", "externo"} else "propio"


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


def summarize_equipment(data: dict) -> str:
    voip_lines: list[str] = []
    router_lines: list[str] = []
    network_lines: list[str] = []

    router_model = _display_model(_safe(data.get("router", {}).get("modelo", "")))
    ont_model = _display_model(_safe(data.get("ont", {}).get("modelo", "")))
    if router_model:
        router_lines.append(router_model)
    if ont_model:
        router_lines.append(ont_model)

    for team in data.get("equipos", []):
        qty = team.get("cantidad", 1)
        model = _display_model(_safe(team.get("modelo") or team.get("tipo", "Equipo")))
        tipo = _safe(team.get("tipo", "")).lower()
        if tipo in {"telefono", "ata"}:
            voip_lines.append(f"x{qty} {model}")
        elif tipo in {"switch", "wifi", "otro"}:
            network_lines.append(f"x{qty} {model}")

    voip_html = "<br>".join(voip_lines) if voip_lines else "&nbsp;"
    router_html = "<br>".join(router_lines) if router_lines else "&nbsp;"
    network_html = "<br>".join(network_lines) if network_lines else "&nbsp;"
    empty_cell = "<td>&nbsp;</td>"
    summary = [
        "<table style='width:100%;height:100%;border-collapse:collapse;' width='100%' height='100%' cellpadding='4' border='1'>",
        "<tbody>",
        "<tr style='background-color:#A7C942;color:#ffffff;border:1px solid #98bf21;'>"
        "<th align='left'>Puestos Voip</th><th align='left'>Routers/ONT</th><th align='left'>Switches/Otros</th></tr>",
        f"<tr style='border:1px solid #98bf21;'><td>{voip_html}</td><td>{router_html}</td><td>{network_html}</td></tr>",
        f"<tr style='border:1px solid #98bf21;'>{empty_cell}{empty_cell}{empty_cell}</tr>",
        f"<tr style='border:1px solid #98bf21;'>{empty_cell}{empty_cell}{empty_cell}</tr>",
        "</tbody></table>",
    ]
    return "".join(summary)


def build_layout(data: dict) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    validate_input_schema(data)
    template = data.get("template", "oficina_simple")
    if template == "rack":
        return build_rack_layout(data)
    if template == "multisede":
        return build_multisite_layout(data)
    return build_office_layout(data, include_switch=(template == "con_switch"))


def _internet_metric_label(internet: dict) -> str:
    tipo = _safe(internet.get("tipo", ""))
    if "4G MONITORIZADO" in tipo.upper():
        return _safe(internet.get("capacidad", ""))
    return _safe(internet.get("velocidad", ""))


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
    nodes.extend(
        [
            NodeSpec(
                key="ont",
                kind="device",
                label=(
                    f"<b>ONT</b><br><b>{_safe(internet.get('tipo', ''))} "
                    f"{_internet_metric_label(internet)}</b>"
                    f"<br>{_safe(internet.get('proveedor', ''))}"
                ),
                model=data.get("ont", {}).get("modelo", "ONT"),
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
        total_width = DEVICE_WIDTH * 2 + DUAL_SWITCH_GAP
        start_x = router_node.x + (router_node.width - total_width) // 2
        switch_tel = _make_switch_node("switch", switches[0], start_x, switch_y)
        switch_datos = _make_switch_node(
            "switch_datos",
            switches[1],
            start_x + DEVICE_WIDTH + DUAL_SWITCH_GAP,
            switch_y,
        )
        nodes.extend([switch_tel, switch_datos])
        edges.append(
            EdgeSpec(
                "router",
                "switch",
                label="ETH3-LAN",
                exit_x=_anchor_exit_x(router_node, switch_tel),
                exit_y=1.0,
                entry_x=0.5,
                entry_y=0.0,
                waypoints=_router_switch_waypoints(router_node, switch_tel, lane_index=0),
                label_offset_x=-24,
                label_offset_y=-32,
            )
        )
        edges.append(
            EdgeSpec(
                "router",
                "switch_datos",
                label="ETH4-LAN",
                exit_x=_anchor_exit_x(router_node, switch_datos),
                exit_y=1.0,
                entry_x=0.5,
                entry_y=0.0,
                waypoints=_router_switch_waypoints(router_node, switch_datos, lane_index=1),
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
            label_offset_x=10,
            label_offset_y=-30,
        )
    )
    return True, False


def _device_anchor(
    team: dict,
    *,
    has_switch: bool,
    has_dual_switch: bool,
    switch_telefonia: bool,
) -> str:
    if not has_switch:
        return "router"
    if has_dual_switch:
        return "switch" if _is_telephony_equipment(team) else "switch_datos"
    if switch_telefonia:
        return "switch"
    if _is_telephony_equipment(team):
        return "router"
    return "switch"


@dataclass
class _DeviceRowLayout:
    anchor_node: NodeSpec
    total_slots: int
    max_per_row: int
    equipo_y: int
    row_step: int
    constrain_to_anchor: bool = False


def _compute_anchor_row_layout(anchor_node: NodeSpec, device_equipos: list, *, constrain_to_anchor: bool = False) -> _DeviceRowLayout:
    total_slots = _count_device_slots(device_equipos)
    has_dect_handsets = any(_dect_handset_key(_normalized_model(team)) for team in device_equipos)
    max_dect_stack = _max_dect_stack_depth(device_equipos) if has_dect_handsets else 1
    equipo_y = anchor_node.y + anchor_node.height + DEVICE_ROW_GAP
    if constrain_to_anchor:
        max_per_row, _ = _max_slots_for_anchor(total_slots, anchor_node) if total_slots else (1, 0)
    else:
        max_per_row, _ = _max_slots_per_row(total_slots) if total_slots else (1, MIN_SLOT_SPACING)
    row_step = DEVICE_HEIGHT + (DECT_ROW_EXTRA if has_dect_handsets else 95)
    if max_dect_stack > 1:
        row_step += (max_dect_stack - 1) * DECT_HANDSET_STACK_STEP
    return _DeviceRowLayout(
        anchor_node=anchor_node,
        total_slots=total_slots,
        max_per_row=max_per_row,
        equipo_y=equipo_y,
        row_step=row_step,
        constrain_to_anchor=constrain_to_anchor,
    )


def _compute_device_row_layout(
    nodes: list[NodeSpec],
    device_equipos: list,
    *,
    has_switch: bool,
    has_dual_switch: bool,
) -> _DeviceRowLayout:
    anchor_node = _layout_anchor_node(nodes, has_switch=has_switch, has_dual_switch=has_dual_switch)
    layout = _compute_anchor_row_layout(anchor_node, device_equipos)
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
    telefonia_equipos = [
        eq
        for eq in device_equipos
        if _device_anchor(
            eq,
            has_switch=True,
            has_dual_switch=True,
            switch_telefonia=switch_telefonia,
        )
        == "switch"
    ]
    datos_equipos = [
        eq
        for eq in device_equipos
        if _device_anchor(
            eq,
            has_switch=True,
            has_dual_switch=True,
            switch_telefonia=switch_telefonia,
        )
        == "switch_datos"
    ]
    return {
        "switch": _compute_anchor_row_layout(switch_tel, telefonia_equipos, constrain_to_anchor=True),
        "switch_datos": _compute_anchor_row_layout(switch_datos, datos_equipos, constrain_to_anchor=True),
    }


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
    switch_port_indices: dict[str, int] | None = None
    slot_indices: dict[str, int] | None = None
    bus_lane_counters: dict[str, int] | None = None
    dect_base_registry: dict[str, str] | None = None
    ordered_base_keys: list[str] | None = None
    handsets_on_base: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.switch_port_indices is None:
            self.switch_port_indices = {"switch": 1, "switch_datos": 1}
        if self.slot_indices is None:
            self.slot_indices = {}
        if self.bus_lane_counters is None:
            self.bus_lane_counters = {}
        if self.dect_base_registry is None:
            self.dect_base_registry = {}
        if self.ordered_base_keys is None:
            self.ordered_base_keys = []
        if self.handsets_on_base is None:
            self.handsets_on_base = {}
        if self.has_switch:
            self.router_port_index = 5 if self.has_dual_switch else 4

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
            constrain_to_anchor=layout.constrain_to_anchor,
        )
        x = start_x + col * spacing
        y = layout.equipo_y + row_num * layout.row_step
        if self.row_layouts is not None:
            self.slot_indices[anchor_key] = slot_index + 1
        else:
            self.slot_index += 1
        return x, y, y

    def next_port_labels(self, anchor_key: str) -> tuple[str, str]:
        if anchor_key in SWITCH_ANCHOR_KEYS:
            port = f"ETH{self.switch_port_indices[anchor_key]}"
            self.switch_port_indices[anchor_key] += 1
            return port, port
        port = f"ETH{self.router_port_index}"
        cable_label = f"{port}-LAN"
        self.router_port_index += 1
        return cable_label, port

    def place_edge(self, anchor_key: str, target_key: str, label: str, row_top_y: int | None = None) -> None:
        anchor = next(node for node in self.nodes if node.key == anchor_key)
        target = next(node for node in self.nodes if node.key == target_key)
        exit_x = _anchor_exit_x(anchor, target) if anchor_key in SWITCH_ANCHOR_KEYS | {"router"} else 0.5
        lane_index = self.bus_lane_counters.get(anchor_key, 0)
        self.bus_lane_counters[anchor_key] = lane_index + 1
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


def _create_dect_base(state: _DevicePlacementState, team: dict, normalized_model: str) -> str:
    registry_key = _dect_registry_key(team, normalized_model)
    base_model_name = _display_model(_resolve_dect_base(team, normalized_model))
    base_key = f"team_{state.team_index}"
    anchor_key = state.anchor_for(team)
    base_x, base_y, row_top_y = state.next_position(anchor_key)
    cable_label, port_label = state.next_port_labels(anchor_key)
    state.nodes.append(
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
    state.place_edge(anchor_key, base_key, cable_label, row_top_y)
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

    base_node = next(node for node in state.nodes if node.key == base_key)
    stack_index = state.handsets_on_base.get(base_key, 0)
    handset_y = base_node.y + DECT_HANDSET_OFFSET_Y + stack_index * DECT_HANDSET_STACK_STEP
    key = f"team_{state.team_index}"
    handset_label = _equipment_label(team, extension=extension)
    state.nodes.append(
        NodeSpec(
            key=key,
            kind="device",
            label=handset_label,
            model=team.get("modelo", team.get("tipo", "Equipo")),
            x=base_node.x,
            y=handset_y,
            width=150,
            height=150,
            meta={
                "tipo": team.get("tipo"),
                "dect_role": "handset",
                "propiedad": _ownership(team),
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
    cable_label, port_label = state.next_port_labels(anchor_key)
    state.nodes.append(
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
            },
        )
    )
    if is_dect_base:
        registry_key = _display_model(_safe(team.get("modelo"))).upper()
        if registry_key and registry_key not in state.dect_base_registry:
            state.dect_base_registry[registry_key] = key
            state.ordered_base_keys.append(key)
        state.handsets_on_base[key] = state.handsets_on_base.get(key, 0)
    state.place_edge(anchor_key, key, cable_label, row_top_y)
    state.team_index += 1


def _place_equipment_rows(
    data: dict,
    state: _DevicePlacementState,
) -> None:
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
