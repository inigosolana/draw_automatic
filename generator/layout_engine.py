from __future__ import annotations

from dataclasses import dataclass
from .aliases import resolve_alias


DECT_BASE_MODELS = {"w60b", "w70b", "w80b", "w90b"}
DECT_HANDSET_MODELS = {"w71h", "w53", "w53h", "w73", "w73h"}


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


@dataclass
class EdgeSpec:
    source: str
    target: str
    label: str | None = None
    exit_x: float = 1.0
    exit_y: float = 0.5
    entry_x: float = 0.5
    entry_y: float = 0.5


def _safe(value: object) -> str:
    return "" if value is None else str(value)


def _normalized_model(team: dict) -> str:
    return _safe(team.get("modelo", team.get("tipo", ""))).strip().lower()


def _display_model(value: str) -> str:
    return resolve_alias(value or "")


def _router_label(router: dict) -> str:
    alias = _display_model(_safe(router.get("modelo", "Router")))
    ip_value = _safe(router.get("ip", ""))
    if alias == "CHATEAU":
        return f"<b>CHATEAU</b><br>LAN {ip_value}" if ip_value else "<b>CHATEAU</b>"
    return f"<b>{alias or 'Router'}</b><br>{ip_value}"


def _equipment_label(team: dict, extension: str = "") -> str:
    display_model = _display_model(_safe(team.get("modelo", team.get("tipo", "Equipo"))))
    parts = [f"<b>{display_model}</b>"]
    if extension:
        parts.append(f"EXT {_safe(extension)}")
    if team.get("serial_number"):
        parts.append(f"SN {_safe(team.get('serial_number'))}")
    if team.get("mac"):
        parts.append(f"MAC {_safe(team.get('mac'))}")
    return "<br>".join(parts)


def _ownership(team: dict) -> str:
    return "ajeno" if _safe(team.get("propiedad", "propio")).lower() in {"ajeno", "no", "externo"} else "propio"


def validate_input_data(data: dict) -> list[str]:
    warnings: list[str] = []
    internet = data.get("internet", {})
    router_model = _display_model(_safe(data.get("router", {}).get("modelo", "")))
    if (
        "BACK UP" in _safe(internet.get("tipo", "")).upper()
        and router_model != "CHATEAU"
        and not internet.get("backup")
    ):
        warnings.append("La conexion Fibra + Backup con hAP ac2 necesita seleccionar WAP LTE o TELTONIKA para ETH2.")
    for team in data.get("equipos", []):
        qty = int(team.get("cantidad", 1))
        extensions = team.get("extensiones") or []
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
        elif tipo in {"switch", "wifi", "otro"} and model in {"CHATEAU", "ONT ZTE", "Microtik_hAPc", "Router ZTE"}:
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
    template = data.get("template", "oficina_simple")
    if template == "rack":
        return build_rack_layout(data)
    if template == "multisede":
        return build_multisite_layout(data)
    return build_office_layout(data, include_switch=(template == "con_switch"))


def build_office_layout(data: dict, include_switch: bool) -> tuple[list[NodeSpec], list[EdgeSpec]]:
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
        NodeSpec(
            key="ont",
            kind="device",
            label=(
                f"<b>ONT</b><br><b>{_safe(data.get('internet', {}).get('tipo', ''))} "
                f"{_safe(data.get('internet', {}).get('velocidad', ''))}</b>"
                f"<br>{_safe(data.get('internet', {}).get('proveedor', ''))}"
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
    edges: list[EdgeSpec] = [
        EdgeSpec("inet", "ont", exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5),
        EdgeSpec("ont", "router", label="ETH1-WAN", exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5),
    ]

    current_anchor = "router"
    internet = data.get("internet", {})
    router_model = _display_model(_safe(data.get("router", {}).get("modelo", "")))
    backup_model = _safe(internet.get("backup", ""))
    has_backup_service = "BACK UP" in _safe(internet.get("tipo", "")).upper()
    if has_backup_service and router_model == "CHATEAU":
        router_node = next(node for node in nodes if node.key == "router")
        router_node.label += "<br>BACKUP 4G INTEGRADO"
    elif has_backup_service and backup_model:
        nodes.append(
            NodeSpec(
                key="backup",
                kind="device",
                label=f"<b>{backup_model}</b><br>BACKUP",
                model=backup_model,
                x=470,
                y=330,
                width=150,
                height=120,
                meta={"propiedad": "propio"},
            )
        )
        edges.append(
            EdgeSpec("router", "backup", label="ETH2-BACKUP", exit_x=0.5, exit_y=1.0, entry_x=0.5, entry_y=0.0)
        )

    switches = [eq for eq in data.get("equipos", []) if eq.get("tipo") == "switch"]
    if include_switch and switches:
        switch = switches[0]
        nodes.append(
            NodeSpec(
                key="switch",
                kind="device",
                label=f"<b>{_safe(switch.get('modelo', 'Switch'))}</b>",
                model=switch.get("modelo", "Switch"),
                x=720,
                y=120,
                width=150,
                height=150,
                meta={"propiedad": _ownership(switch)},
            )
        )
        edges.append(EdgeSpec("router", "switch", label="ETH3-LAN", exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5))
        current_anchor = "switch"

    equipo_x = 250
    equipo_y = 530
    column = 0
    row = 0
    team_index = 1
    router_port_index = 3
    switch_port_index = 1
    dect_base_keys: list[str] = []

    def next_position() -> tuple[int, int]:
        return equipo_x + column * 180, equipo_y + row * 190

    def advance_position() -> None:
        nonlocal column, row
        column += 1
        if column == 3:
            column = 0
            row += 1

    for team in data.get("equipos", []):
        if team.get("tipo") == "switch":
            continue
        qty = int(team.get("cantidad", 1))
        exts = team.get("extensiones", [])
        normalized_model = _normalized_model(team)
        is_dect_base = normalized_model in DECT_BASE_MODELS
        is_dect_handset = normalized_model in DECT_HANDSET_MODELS
        for idx in range(qty):
            extension = exts[idx] if idx < len(exts) else ""
            label = _equipment_label(team, extension=extension)
            key = f"team_{team_index}"
            if is_dect_handset and dect_base_keys:
                base_index = min(idx, len(dect_base_keys) - 1)
                base_node = next(node for node in nodes if node.key == dect_base_keys[base_index])
                node_x = base_node.x
                node_y = base_node.y + 190
            else:
                node_x, node_y = next_position()
            nodes.append(
                NodeSpec(
                    key=key,
                    kind="device",
                    label=label,
                    model=team.get("modelo", team.get("tipo", "Equipo")),
                    x=node_x,
                    y=node_y,
                    width=150,
                    height=150,
                    meta={
                        "tipo": team.get("tipo"),
                        "dect_role": "handset" if is_dect_handset else ("base" if is_dect_base else ""),
                        "propiedad": _ownership(team),
                    },
                )
            )
            if is_dect_base:
                dect_base_keys.append(key)
            if not is_dect_handset:
                if current_anchor == "switch":
                    cable_label = f"SW{switch_port_index}-ETH"
                    switch_port_index += 1
                else:
                    cable_label = f"ETH{router_port_index}-LAN"
                    router_port_index += 1
                edges.append(
                    EdgeSpec(
                        current_anchor,
                        key,
                        label=cable_label,
                        exit_x=0.5,
                        exit_y=1.0,
                        entry_x=0.5,
                        entry_y=0.0,
                    )
                )
                advance_position()
            team_index += 1

    nodes.append(
        NodeSpec(
            key="summary_title",
            kind="plain_text",
            label="Resumen Equipos",
            x=897,
            y=70,
            width=120,
            height=30,
        )
    )
    nodes.append(
        NodeSpec(
            key="summary",
            kind="table",
            label=summarize_equipment(data),
            x=765,
            y=110,
            width=385,
            height=170,
        )
    )
    return nodes, edges


def build_rack_layout(data: dict) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    nodes, edges = build_office_layout(data, include_switch=True)
    for node in nodes:
        if node.key == "router":
            node.y = 240
        elif node.key == "switch":
            node.x = 970
            node.y = 240
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
