from __future__ import annotations

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
SUMMARY_WIDTH = 260
SUMMARY_TITLE_Y = 75
SUMMARY_Y = 105
SUMMARY_HEIGHT = 165
DEVICE_WIDTH = 150
DEVICE_HEIGHT = 150
DECT_HANDSET_OFFSET_Y = 195
SLOT_SPACING = 235
MIN_SLOT_SPACING = 230
MIN_LEFT_MARGIN = 60
DEVICE_ROW_GAP = 165
DECT_ROW_EXTRA = 110
SWITCH_FALLBACK_ICON = "TP-Link 8P"
ROUTER_BACKUP_GAP = 70
ROUTER_SWITCH_GAP = 90


def _count_device_slots(equipos: list) -> int:
    total = 0
    for index, team in enumerate(equipos):
        if team.get("tipo") == "switch":
            continue
        validated = ValidatedEquipment.from_dict(team, index)
        total += validated.cantidad
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


def _device_row_layout(total_slots: int, anchor: NodeSpec, max_right: int = SUMMARY_X - 20) -> tuple[int, int]:
    _, spacing = _row_layout(total_slots, max_right)
    row_width = (total_slots - 1) * spacing + DEVICE_WIDTH
    centered_start = anchor.x + (anchor.width - row_width) // 2
    start_x = max(MIN_LEFT_MARGIN, min(centered_start, max_right - row_width))
    return start_x, spacing


def _max_slots_per_row(total_slots: int) -> tuple[int, int]:
    for slots_in_row in range(total_slots, 0, -1):
        _, spacing = _row_layout(slots_in_row)
        row_width = (slots_in_row - 1) * spacing + DEVICE_WIDTH
        if row_width <= SUMMARY_X - 20 - MIN_LEFT_MARGIN:
            return slots_in_row, spacing
    return 1, 0


def _anchor_exit_x(anchor: NodeSpec, target: NodeSpec) -> float:
    target_center = target.x + target.width / 2
    ratio = (target_center - anchor.x) / anchor.width
    return max(0.06, min(0.94, ratio))


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
        elif tipo in {"switch", "wifi", "otro"} and model in {"CHATEAU", "ONT ZTE", "Microtik_hAPc", "MikroTik hAP ac3", "Router ZTE"}:
            router_lines.append(model)

    voip_html = "<br>".join(voip_lines) if voip_lines else "&nbsp;"
    router_html = "<br>".join(router_lines) if router_lines else "&nbsp;"
    summary = [
        "<table style='width:100%;height:100%;border-collapse:collapse;' width='100%' height='100%' cellpadding='4' border='1'>",
        "<tbody>",
        "<tr style='background-color:#A7C942;color:#ffffff;border:1px solid #98bf21;'><th align='left'>Puestos Voip</th><th align='left'>Routers/ONT</th></tr>",
        f"<tr style='border:1px solid #98bf21;'><td>{voip_html}</td><td>{router_html}</td></tr>",
        "<tr style='border:1px solid #98bf21;'><td>&nbsp;</td><td>&nbsp;</td></tr>",
        "<tr style='border:1px solid #98bf21;'><td>&nbsp;</td><td>&nbsp;</td></tr>",
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


def build_office_layout(data: dict, include_switch: bool) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    internet = data.get("internet", {})
    is_4g_monitored = _is_4g_monitored(internet)
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
    edges: list[EdgeSpec] = []

    if is_4g_monitored:
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
    else:
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
                EdgeSpec("ont", "router", label="ETH1-WAN", exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5),
            ]
        )

    current_anchor = "router"
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
                label_offset_y=-12,
            )
        )

    switches = [eq for eq in data.get("equipos", []) if eq.get("tipo") == "switch"]
    has_switch = include_switch and bool(switches)
    if has_switch:
        router_node = next(node for node in nodes if node.key == "router")
        switch = switches[0]
        switch_width = 150
        switch_height = 150
        nodes.append(
            NodeSpec(
                key="switch",
                kind="device",
                label=f"<b>{_safe(switch.get('modelo', 'Switch'))}</b>",
                model=switch.get("modelo", "Switch"),
                x=router_node.x + (router_node.width - switch_width) // 2,
                y=router_node.y + router_node.height + ROUTER_SWITCH_GAP,
                width=switch_width,
                height=switch_height,
                meta={"propiedad": _ownership(switch)},
                icon_model=SWITCH_FALLBACK_ICON,
            )
        )
        edges.append(
            EdgeSpec(
                "router",
                "switch",
                label="ETH3-LAN",
                exit_x=0.5,
                exit_y=1.0,
                entry_x=0.5,
                entry_y=0.0,
                label_offset_x=18,
                label_offset_y=-36,
            )
        )
        current_anchor = "switch"

    summary_title_y = SUMMARY_TITLE_Y
    summary_y = SUMMARY_Y

    device_equipos = [eq for eq in data.get("equipos", []) if eq.get("tipo") != "switch"]
    total_slots = _count_device_slots(device_equipos)
    has_dect_handsets = any(_dect_handset_key(_normalized_model(team)) for team in device_equipos)
    anchor_node = next(node for node in nodes if node.key == current_anchor)
    backup_node = next((n for n in nodes if n.key == "backup"), None)
    anchor_bottom = anchor_node.y + anchor_node.height
    if backup_node and not has_switch:
        anchor_bottom = max(anchor_bottom, backup_node.y + backup_node.height)
    equipo_y = anchor_bottom + DEVICE_ROW_GAP
    max_per_row, _ = _max_slots_per_row(total_slots) if total_slots else (1, MIN_SLOT_SPACING)
    row_step = DEVICE_HEIGHT + (DECT_ROW_EXTRA if has_dect_handsets else 95)

    slot_index = 0
    team_index = 1
    router_port_index = 3
    switch_port_index = 1
    dect_base_keys: list[str] = []

    def next_position() -> tuple[int, int]:
        nonlocal slot_index
        row_num = slot_index // max_per_row
        col = slot_index % max_per_row
        slots_in_row = min(max_per_row, total_slots - row_num * max_per_row)
        start_x, spacing = _device_row_layout(slots_in_row, anchor_node)
        x = start_x + col * spacing
        y = equipo_y + row_num * row_step
        slot_index += 1
        return x, y

    def next_port_labels() -> tuple[str, str]:
        nonlocal router_port_index, switch_port_index
        if current_anchor == "switch":
            port = f"SW{switch_port_index}"
            switch_port_index += 1
            return "", port
        port = f"ETH{router_port_index}"
        cable_label = f"{port}-LAN"
        router_port_index += 1
        return cable_label, port

    def place_edge(anchor_key: str, target_key: str, label: str) -> None:
        anchor = next(node for node in nodes if node.key == anchor_key)
        target = next(node for node in nodes if node.key == target_key)
        exit_x = _anchor_exit_x(anchor, target) if anchor_key in {"switch", "router"} else 0.5
        waypoints: tuple[tuple[int, int], ...] | None = None
        label_offset_x = 0
        label_offset_y = -14
        if anchor_key == "switch":
            waypoints = None
        elif anchor_key == "router" and label and label.endswith("-LAN"):
            target_center = target.x + target.width // 2
            bus_y = target.y - 90
            waypoints = ((target_center, bus_y),)
            label_offset_x = 16
            label_offset_y = -((target.y - bus_y) // 2 + 8)
        edges.append(
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

    for team_index_in_data, team in enumerate(data.get("equipos", [])):
        if team.get("tipo") == "switch":
            continue
        validated = ValidatedEquipment.from_dict(team, team_index_in_data)
        qty = validated.cantidad
        exts = validated.extensiones
        normalized_model = _normalized_model(team)
        is_dect_base = _is_dect_base(normalized_model)
        is_dect_handset = _dect_handset_key(normalized_model) is not None
        for idx in range(qty):
            extension = exts[idx] if idx < len(exts) else team.get("extension", "")
            if is_dect_handset:
                if idx >= len(dect_base_keys):
                    base_key = f"team_{team_index}"
                    base_model_name = _resolve_dect_base(team, normalized_model)
                    base_x, base_y = next_position()
                    cable_label, port_label = next_port_labels()
                    nodes.append(
                        NodeSpec(
                            key=base_key,
                            kind="device",
                            label=_equipment_label(
                                {"modelo": base_model_name},
                                port_label=port_label,
                            ),
                            model=base_model_name,
                            x=base_x,
                            y=base_y,
                            width=150,
                            height=150,
                            meta={"tipo": "base_dect", "dect_role": "base", "propiedad": _ownership(team)},
                        )
                    )
                    place_edge(current_anchor, base_key, cable_label)
                    dect_base_keys.append(base_key)
                    team_index += 1
                base_index = min(idx, len(dect_base_keys) - 1)
                base_node = next(node for node in nodes if node.key == dect_base_keys[base_index])
                key = f"team_{team_index}"
                handset_label = _equipment_label(team, extension=extension)
                nodes.append(
                    NodeSpec(
                        key=key,
                        kind="device",
                        label=handset_label,
                        model=team.get("modelo", team.get("tipo", "Equipo")),
                        x=base_node.x,
                        y=base_node.y + DECT_HANDSET_OFFSET_Y,
                        width=150,
                        height=150,
                        meta={
                            "tipo": team.get("tipo"),
                            "dect_role": "handset",
                            "propiedad": _ownership(team),
                        },
                    )
                )
                edges.append(
                    EdgeSpec(
                        dect_base_keys[base_index],
                        key,
                        label="DECT",
                        exit_x=0.5,
                        exit_y=1.0,
                        entry_x=0.5,
                        entry_y=0.0,
                    )
                )
                team_index += 1
                continue
            key = f"team_{team_index}"
            node_x, node_y = next_position()
            cable_label, port_label = next_port_labels()
            nodes.append(
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
                dect_base_keys.append(key)
            place_edge(current_anchor, key, cable_label)
            team_index += 1

    nodes.append(
        NodeSpec(
            key="summary_title",
            kind="plain_text",
            label="Resumen Equipos",
            x=SUMMARY_X + 17,
            y=summary_title_y,
            width=120,
            height=30,
        )
    )
    nodes.append(
        NodeSpec(
            key="summary",
            kind="table",
            label=summarize_equipment(data),
            x=SUMMARY_X,
            y=summary_y,
            width=SUMMARY_WIDTH,
            height=SUMMARY_HEIGHT,
        )
    )
    return nodes, edges


def build_rack_layout(data: dict) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    nodes, edges = build_office_layout(data, include_switch=True)
    router = next(node for node in nodes if node.key == "router")
    for node in nodes:
        if node.key == "router":
            node.y = 240
        elif node.key == "switch":
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
