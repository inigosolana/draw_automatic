"""Parser INVERSO: de un diagrama draw.io (generado por esta app) de vuelta a
datos de formulario.

Se usa para editar un diagrama existente reusando el flujo de creación: se
recuperan sus terminales/dispositivos/conectividad, se fusionan con lo nuevo de
una OT y se regenera un diagrama rico.

FIABILIDAD: los terminales son literales en la etiqueta (modelo/EXT/SN/MAC/IP y
la propiedad por color) → recuperación fiable. La conectividad (tipo/velocidad/
proveedor/router/ONT/backup) es best-effort porque el router aparece con el
nombre de la librería, no con el valor exacto del formulario.
"""

from __future__ import annotations

import html
import re

from defusedxml.ElementTree import fromstring as _xml_fromstring

_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_ETH = re.compile(r"^ETH\d+$", re.IGNORECASE)


def _lines(value: str) -> list[str]:
    """Convierte el value HTML de un nodo en líneas de texto plano."""
    text = _BR.sub("\n", value or "")
    text = _TAG.sub("", text)
    return [html.unescape(line).strip() for line in text.split("\n") if line.strip()]


def _ownership_from_style(style: str) -> str:
    low = (style or "").lower()
    if "#d00000" in low:
        return "ajeno"
    return "propio"  # verde (#008000) o por defecto


def _parse_terminal(lines: list[str], style: str) -> dict | None:
    # Formato: [ETHx?, MODELO, EXT n, SN x, MAC x, IP x] (ETH y campos opcionales).
    body = [ln for ln in lines if not _ETH.match(ln)]
    if not body:
        return None
    model = body[0].strip()
    if not model:
        return None
    term = {"model": model, "extension": "", "serial": "", "mac": "", "ip": "",
            "ownership": _ownership_from_style(style), "dect_base": ""}
    for ln in body[1:]:
        m = re.match(r"^EXT\s+(.+)$", ln, re.IGNORECASE)
        if m:
            term["extension"] = m.group(1).strip()
            continue
        m = re.match(r"^SN\s+(.+)$", ln, re.IGNORECASE)
        if m:
            term["serial"] = m.group(1).strip()
            continue
        m = re.match(r"^MAC\s+(.+)$", ln, re.IGNORECASE)
        if m:
            term["mac"] = m.group(1).strip()
            continue
        m = re.match(r"^IP\s+(.+)$", ln, re.IGNORECASE)
        if m:
            term["ip"] = m.group(1).strip()
            continue
        m = re.match(r"^base\s+(.+)$", ln, re.IGNORECASE)
        if m:
            term["dect_base"] = m.group(1).strip()
    return term


def parse_drawio_to_form(xml: str) -> dict:
    """Extrae {terminals, connectivity_text} de un diagrama draw.io nuestro.

    - terminals: lista de dicts (model/extension/serial/mac/ip/ownership/dect_base).
    - connectivity_text: texto libre de los nodos de conectividad (para que el
      mapeo de tipo/proveedor/velocidad lo resuelva equipment_detection).
    Devuelve {} si el XML no es parseable.
    """
    try:
        root = _xml_fromstring(xml)
    except Exception:
        return {"terminals": [], "connectivity_text": ""}

    terminals: list[dict] = []
    connectivity_bits: list[str] = []
    for cell in root.iter("mxCell"):
        value = cell.get("value") or ""
        if not value:
            continue
        style = cell.get("style") or ""
        lines = _lines(value)
        joined = " ".join(lines)
        # Terminal: lleva una extensión "EXT n".
        if any(re.match(r"^EXT\s+\S", ln, re.IGNORECASE) for ln in lines):
            term = _parse_terminal(lines, style)
            if term:
                terminals.append(term)
            continue
        # Conectividad: nodos con tipo de internet / router / backup.
        low = joined.lower()
        if any(k in low for k in ("fibra", "4g monitor", "backup", "ont", "router", "mikrotik", "chateau", "wap lte", "teltonika")):
            # Ignorar la tabla resumen y la cabecera.
            if "resumen equipos" in low or "puestos voip" in low:
                continue
            connectivity_bits.append(joined)

    return {"terminals": terminals, "connectivity_text": " | ".join(connectivity_bits)}
