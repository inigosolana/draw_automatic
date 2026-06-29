"""Formato de etiquetas y normalización de modelos para el dibujado.

Funciones puras (sin geometría ni estado) extraídas de layout_engine para
reducir su tamaño. Convierten datos de equipo/router/internet en el texto HTML
que se pinta en los nodos del diagrama.
"""

from __future__ import annotations

import re

from .aliases import resolve_alias

SWITCH_FALLBACK_ICON = "TP-Link 8P"


def safe(value: object) -> str:
    return "" if value is None else str(value)


def normalized_model(team: dict) -> str:
    return safe(team.get("modelo", team.get("tipo", ""))).strip().lower()


def display_model(value: str) -> str:
    return resolve_alias(value or "")


def switch_icon_model(model: str) -> str:
    without_prefix = re.sub(r"^switch\s+", "", safe(model).strip(), flags=re.IGNORECASE)
    resolved = display_model(without_prefix)
    return resolved or SWITCH_FALLBACK_ICON


def is_4g_monitored(internet: dict) -> bool:
    return "4G MONITORIZADO" in safe(internet.get("tipo", "")).upper()


def internet_metric_label(internet: dict) -> str:
    tipo = safe(internet.get("tipo", ""))
    if "4G MONITORIZADO" in tipo.upper():
        return safe(internet.get("capacidad", ""))
    return safe(internet.get("velocidad", ""))


def router_label(router: dict, internet: dict | None = None) -> str:
    alias = display_model(safe(router.get("modelo", "Router")))
    ip_value = safe(router.get("ip", ""))
    if alias == "CHATEAU":
        label = f"<b>CHATEAU</b><br>LAN {ip_value}" if ip_value else "<b>CHATEAU</b>"
    else:
        label = f"<b>{alias or 'Router'}</b><br>{ip_value}"
    if internet and is_4g_monitored(internet):
        label += (
            f"<br><b>{safe(internet.get('tipo', ''))} "
            f"{internet_metric_label(internet)}</b>"
            f"<br>{safe(internet.get('proveedor', ''))}"
        )
    return label


def equipment_label(team: dict, extension: str = "", port_label: str = "") -> str:
    model = display_model(safe(team.get("modelo", team.get("tipo", "Equipo"))))
    parts: list[str] = []
    if port_label:
        parts.append(f"<b>{safe(port_label)}</b>")
    parts.append(f"<b>{model}</b>")
    if extension:
        parts.append(f"EXT {safe(extension)}")
    if team.get("serial_number"):
        parts.append(f"SN {safe(team.get('serial_number'))}")
    if team.get("mac"):
        parts.append(f"MAC {safe(team.get('mac'))}")
    if team.get("ip"):
        parts.append(f"IP {safe(team.get('ip'))}")
    return "<br>".join(parts)


def ownership(team: dict) -> str:
    if safe(team.get("propiedad", "propio")).lower() in {"ajeno", "no", "externo"}:
        return "ajeno"
    return "propio"
