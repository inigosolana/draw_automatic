from __future__ import annotations

from dataclasses import dataclass


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
    exit_y: float = 0.5
    entry_y: float = 0.5


def summarize_equipment(data: dict) -> str:
    lines = []
    for team in data.get("equipos", []):
        qty = team.get("cantidad", 1)
        model = team.get("modelo") or team.get("tipo", "Equipo")
        lines.append(f"x{qty} {model}")
    total = sum(int(team.get("cantidad", 1)) for team in data.get("equipos", []))
    summary = [
        "<table style='width:100%;height:100%;border-collapse:collapse;' width='100%' height='100%' cellpadding='4' border='1'>",
        "<tbody>",
        "<tr style='background-color:#A7C942;color:#ffffff;border:1px solid #98bf21;'><th align='left'>Cliente</th><th align='left'>Internet</th><th align='left'>Total</th></tr>",
        f"<tr style='border:1px solid #98bf21;'><td>{data['cliente']}</td><td>{data.get('internet', {}).get('tipo', '')} {data.get('internet', {}).get('velocidad', '')}</td><td>{total}</td></tr>",
        "<tr style='background-color:#EAF2D3;border:1px solid #98bf21;'><th align='left'>Sede</th><th align='left'>Router</th><th align='left'>Equipos</th></tr>",
        f"<tr style='border:1px solid #98bf21;'><td>{data['sede']}</td><td>{data.get('router', {}).get('modelo', '')}</td><td>{', '.join(lines) or '-'}</td></tr>",
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
                f"<div style='text-align:start;'><b>{data['cliente']}</b> - {data.get('cif', '')}</div>"
                f"<div style='text-align:start;'>{data['sede']}</div>"
                f"<div style='text-align:start;'>{data['direccion']}</div>"
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
            label=f"<b>ONT</b><br><b>{data.get('internet', {}).get('tipo', '')} {data.get('internet', {}).get('velocidad', '')}</b>",
            model=data.get("ont", {}).get("modelo", "ONT"),
            x=240,
            y=120,
            width=150,
            height=150,
        ),
        NodeSpec(
            key="router",
            kind="device",
            label=(
                f"<b>{data.get('router', {}).get('modelo', 'Router')}</b><br>"
                f"{data.get('router', {}).get('ip', '')}"
            ),
            model=data.get("router", {}).get("modelo", "Router"),
            x=470,
            y=120,
            width=150,
            height=150,
        ),
    ]
    edges: list[EdgeSpec] = [
        EdgeSpec("inet", "ont", exit_y=0.25, entry_y=0.0),
        EdgeSpec("ont", "router", label="ETH1-WAN", exit_y=0.5, entry_y=0.0),
    ]

    current_anchor = "router"
    switches = [eq for eq in data.get("equipos", []) if eq.get("tipo") == "switch"]
    if include_switch and switches:
        switch = switches[0]
        nodes.append(
            NodeSpec(
                key="switch",
                kind="device",
                label=f"<b>{switch.get('modelo', 'Switch')}</b>",
                model=switch.get("modelo", "Switch"),
                x=720,
                y=120,
                width=150,
                height=150,
            )
        )
        edges.append(EdgeSpec("router", "switch", label="ETH2-LAN1", exit_y=0.5, entry_y=0.0))
        current_anchor = "switch"

    equipo_x = 250
    equipo_y = 530
    column = 0
    row = 0
    team_index = 1
    port_index = 3
    for team in data.get("equipos", []):
        if team.get("tipo") == "switch":
            continue
        qty = int(team.get("cantidad", 1))
        exts = team.get("extensiones", [])
        for idx in range(qty):
            extension = exts[idx] if idx < len(exts) else ""
            label = f"<b>{team.get('modelo', team.get('tipo', 'Equipo'))}</b>"
            if extension:
                label += f"<br>EXT {extension}"
            key = f"team_{team_index}"
            nodes.append(
                NodeSpec(
                    key=key,
                    kind="device",
                    label=label,
                    model=team.get("modelo", team.get("tipo", "Equipo")),
                    x=equipo_x + column * 180,
                    y=equipo_y + row * 190,
                    width=150,
                    height=150,
                    meta={"tipo": team.get("tipo")},
                )
            )
            edges.append(EdgeSpec(current_anchor, key, label=f"ETH{port_index}-LAN{port_index-1}", exit_y=min(0.25 * ((column % 3) + 1), 0.75), entry_y=0.0))
            team_index += 1
            column += 1
            port_index += 1
            if column == 3:
                column = 0
                row += 1

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
        NodeSpec(key="header", kind="text", label=f"<b>{data['cliente']}</b><br>{data['direccion']}", x=860, y=10, width=280, height=60),
        NodeSpec(key="inet", kind="cloud", label="INET", x=480, y=40, width=140, height=90),
    ]
    edges: list[EdgeSpec] = []
    sites = data.get("sedes") or [{"sede": data["sede"], "direccion": data["direccion"]}]
    for index, site in enumerate(sites, start=1):
        x = 120 + (index - 1) * 320
        nodes.append(NodeSpec(key=f"site_{index}", kind="device", label=f"<b>{site.get('sede', f'Sede {index}')}</b><br>{site.get('direccion', '')}", model=site.get("router", {}).get("modelo", data.get("router", {}).get("modelo", "Router")), x=x, y=240, width=150, height=150))
        edges.append(EdgeSpec("inet", f"site_{index}", label=f"VPN {index}", exit_y=0.75, entry_y=0.0))
    nodes.append(NodeSpec(key="summary_title", kind="plain_text", label="Resumen Equipos", x=897, y=150, width=120, height=30))
    nodes.append(NodeSpec(key="summary", kind="table", label=summarize_equipment(data), x=765, y=190, width=385, height=170))
    return nodes, edges
