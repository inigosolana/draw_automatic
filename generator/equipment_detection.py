"""Detección y normalización de modelos de equipo a partir de texto libre.

Reconoce routers, ONTs, backups 4G, bases/terminales DECT, switches, APs y
proveedor/velocidad de internet a partir de los nombres de producto de una OT u
oferta. Centralizado aquí para que tanto `offer_mapper` (texto/HTML de oferta)
como `work_order_json` (payload CRM) usen la MISMA lógica sin que uno dependa del
otro (antes work_order_json importaba estas funciones de offer_mapper).
"""

from __future__ import annotations

import re

DECT_BASE_PATTERN = re.compile(r"\b(w60b|w70b|w80b|w90dm|yealink\s*w90dm)\b", re.IGNORECASE)
DECT_HANDSET_PATTERN = re.compile(r"\b(w71h|w72h|w53h|w73h)\b", re.IGNORECASE)
SIP_TERMINAL_PATTERN = re.compile(r"\b(?:sip[-\s]?t(\d{2})g?|t[-\s]?(\d{2}))\b", re.IGNORECASE)
FANVIL_PATTERN = re.compile(r"\bfanvil\s*(v\d{2})?\b", re.IGNORECASE)
FANVIL_STANDALONE_PATTERN = re.compile(r"\bv(62|64)\b", re.IGNORECASE)

FIBER_PROVIDERS = {
    "fibra pro max velocidad": "AIRE",
    "fibra pro max": "AIRE",
    "movistar(aire)": "AIRE",
    "movistar aire": "AIRE",
    "aire": "AIRE",
    "adamo": "ADAMO",
    "mas movil": "MAS MOVIL",
    "masmovil": "MAS MOVIL",
    "euskaltel": "EUSKALTEL",
    "sarenet orange": "SARENET ORANGE",
    "sarenet": "SARENET",
}

SPEED_PATTERN = re.compile(r"\b(300\s*mb|600\s*mb|1\s*gb)\b", re.IGNORECASE)


def _normalize_dect_base(name: str) -> str:
    match = DECT_BASE_PATTERN.search(name)
    if not match:
        return ""
    token = match.group(1).upper().replace("YEALINK ", "")
    if token == "W90DM":
        return "YEALINK W90DM"
    return token


def _normalize_terminal_model(name: str) -> str:
    handset = DECT_HANDSET_PATTERN.search(name)
    if handset:
        return handset.group(1).upper()
    sip = SIP_TERMINAL_PATTERN.search(name)
    if sip:
        digits = sip.group(1) or sip.group(2)
        return f"T-{digits}"
    if re.search(r"\bx303g?\b", name, re.IGNORECASE):
        return "FANVIL X303G"
    fanvil = FANVIL_PATTERN.search(name)
    if fanvil:
        version = fanvil.group(1)
        return f"FANVIL V{version[1:]}" if version else "FANVIL V62"
    standalone_fanvil = FANVIL_STANDALONE_PATTERN.search(name)
    if standalone_fanvil:
        return f"FANVIL V{standalone_fanvil.group(1)}"
    lowered = name.lower()
    for token in ("t-33", "t-31", "t-30", "t-43", "t-44", "t-73"):
        if token.replace("-", "") in lowered.replace("-", "").replace(" ", ""):
            return token.upper()
    return ""


def _detect_router_model(name: str) -> str:
    lowered = name.lower()
    if _detect_backup_model(name):
        return ""
    if "chateau" in lowered or "s53ug" in lowered or "ax r17" in lowered:
        return "CHATEAU"
    if "hap ac3" in lowered or "ac3" in lowered and "hap" in lowered:
        return "MikroTik hAP ac3"
    if "hap ac2" in lowered or ("ac2" in lowered and "hap" in lowered):
        return "MikroTik hAP ac2"
    if "mikrotik" in lowered:
        return "MikroTik hAP ac2"
    return ""


def _detect_ont_model(name: str, provider: str) -> str:
    lowered = name.lower()
    if "ont" not in lowered and "gpon" not in lowered:
        return ""
    if "adamo" in lowered or provider == "ADAMO":
        return "ONT ADAMO"
    return "ONT ZTE"


def _detect_backup_model(name: str) -> str:
    lowered = name.lower()
    if "teltonika" in lowered:
        return "TELTONIKA"
    if (
        "wap lte" in lowered
        or "wapr" in lowered
        or "ec200a" in lowered
        or re.search(r"\bwap\b", lowered)
        or "router backup especial" in lowered
        or "backup especial 4g" in lowered
    ):
        return "WAP LTE"
    return ""


def _normalize_wifi_ap_model(name: str) -> str:
    lowered = name.lower()
    compact = re.sub(r"[\s\-_]+", "", lowered)
    if any(token in compact for token in ("gwn7660", "gwn7630", "gwn7615", "gwn7610", "gwn7600")):
        return "Grandstream AP"
    if "grandstream" in lowered and "gwn" in lowered:
        return "Grandstream AP"
    return name.strip()


def _detect_device_category(name: str) -> tuple[str, str, str] | None:
    lowered = name.lower()
    if any(token in lowered for token in ("tl-sg1005", "sg1005d", "ls105g")):
        return ("switch", "switch", "TP-LINK-5_PORTS")
    if any(token in lowered for token in ("switch", "swtich", "tp-link", "tp link", "dgs", "firebox")):
        model = name.strip()
        if "switch" not in model.lower():
            model = f"switch {model}"
        return ("switch", "switch", model)
    if any(token in lowered for token in ("deco", "mesh", "access point", "punto de acceso", " gwn", " ruijie", " wifi")):
        return ("ap", "wifi", _normalize_wifi_ap_model(name))
    if "ata" in lowered:
        return ("ata", "ata", "ATA")
    if "nas" in lowered:
        return ("nas", "otro", "nas")
    return None


def _normalize_provider(text: str) -> str:
    lowered = (text or "").lower()
    if "fibra pro max" in lowered:
        return "AIRE"
    for key, value in sorted(FIBER_PROVIDERS.items(), key=lambda item: len(item[0]), reverse=True):
        if key in lowered:
            return value
    return ""


def _normalize_speed(text: str) -> str:
    lowered = (text or "").lower()
    if "fibra pro max" in lowered:
        return "1 GB"
    if "fibra profesional" in lowered or re.search(r"\bfibra\s+pro\b", lowered):
        return "600 MB"

    match = SPEED_PATTERN.search(text or "")
    if not match:
        return ""
    token = match.group(1).upper().replace(" ", " ")
    if token.startswith("1"):
        return "1 GB"
    if token.startswith("600"):
        return "600 MB"
    if token.startswith("300"):
        return "300 MB"
    return ""
