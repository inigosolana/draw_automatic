"""Tabla-resumen de equipos (HTML) que se incrusta como nodo en el diagrama."""

from __future__ import annotations

from .layout_labels import (
    display_model as _display_model,
    safe as _safe,
)


def summarize_equipment(data: dict) -> str:
    voip_lines: list[str] = []
    router_lines: list[str] = []
    network_lines: list[str] = []

    internet = data.get("internet", {})
    router_model = _display_model(_safe(data.get("router", {}).get("modelo", "")))
    ont_model = _display_model(_safe(data.get("ont", {}).get("modelo", "")))
    backup_model = _safe(internet.get("backup", ""))
    if router_model:
        router_lines.append(router_model)
    if ont_model:
        router_lines.append(ont_model)
    if backup_model and router_model != "CHATEAU":
        router_lines.append(_display_model(backup_model))

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
