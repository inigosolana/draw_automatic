from __future__ import annotations

import re

from .library_loader import load_library

SWITCH_MODELS: list[str] = [
    "Swtich_POE_Tenda",
    "Swtich_POE_gestionable_dlink",
    "TP-Link 16P",
    "tp-link-tl-sg1024de-switch-24-puertos-gigabit  02",
    "tp-link-tl-sg1024de-switch-24-puertos-gigabit  01",
    "TP-LIINK",
    "TP-LINK-5_PORTS",
    "DGS 108GL A1 Front",
    "SW tp-link basico",
    "SW_TP-LINK_16PORTs",
    "TP-Link 8P",
]

DEVICE_CATEGORIES: list[dict] = [
    {
        "id": "switch",
        "label": "Switch",
        "tipo": "switch",
        "models": SWITCH_MODELS,
    },
    {
        "id": "firewall",
        "label": "Firewall",
        "tipo": "otro",
        "models": ["Fortinet", "Check Point", "FIREBOX"],
    },
    {
        "id": "ap",
        "label": "Punto de acceso",
        "tipo": "wifi",
        "models": [
            "Grandstream AP",
            "AP_GWN7630",
            "TPLINK_Deco_m4",
            "DECO MESH",
            "RUIJIE AX3000",
            "WIFI",
        ],
    },
    {
        "id": "pc",
        "label": "PC",
        "tipo": "pc",
        "models": ["Pc"],
    },
    {
        "id": "ata",
        "label": "ATA",
        "tipo": "ata",
        "models": ["ATA"],
    },
    {
        "id": "patch",
        "label": "Patch panel",
        "tipo": "otro",
        "models": [
            "patch-panel-24-puertos-categoria-6  02",
            "patch-panel-24-puertos-categoria-6  01",
        ],
    },
    {
        "id": "nas",
        "label": "NAS",
        "tipo": "otro",
        "models": ["nas"],
    },
    {
        "id": "camara",
        "label": "Cámara",
        "tipo": "otro",
        "models": ["CAMARA"],
    },
    {
        "id": "smarttv",
        "label": "Smart TV",
        "tipo": "otro",
        "models": ["SMARTTV"],
    },
    {
        "id": "fax",
        "label": "Fax",
        "tipo": "otro",
        "models": ["Fax"],
    },
    {
        "id": "otros",
        "label": "Otros",
        "tipo": "otro",
        "models": [],
        "custom": True,
    },
]


def _unique_models(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for model in group:
            key = model.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(model)
    return ordered


def _switch_titles_from_library(library) -> list[str]:
    switch_keywords = ("switch", "swtich", "tp-link", "tp link", "dgs", "ls105g")
    discovered: list[str] = []
    for item in library.items:
        title = (item.title or "").strip()
        if not title:
            continue
        lowered = title.lower()
        if any(keyword in lowered for keyword in switch_keywords):
            discovered.append(title)
    return discovered


def build_device_catalog(library_path: str | None = None) -> list[dict]:
    from .web_adapter import resolve_library_path

    library = load_library(resolve_library_path(library_path or "libreria_Ausarta_JUN_2026.xml"))
    categories: list[dict] = []
    for category in DEVICE_CATEGORIES:
        entry = dict(category)
        if entry["id"] == "switch":
            entry["models"] = _unique_models(SWITCH_MODELS, _switch_titles_from_library(library))
        categories.append(entry)
    return categories


def devices_json_to_equipos(raw_json: str) -> list[dict]:
    if not raw_json.strip():
        return []
    import json

    items = json.loads(raw_json)
    if not isinstance(items, list):
        return []

    equipos: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        category_id = str(item.get("category", "")).strip()
        modelo = str(item.get("modelo", "")).strip()
        if not modelo:
            continue
        cantidad = max(1, int(item.get("cantidad", 1) or 1))
        propiedad = str(item.get("propiedad", "propio")).strip().lower() or "propio"
        tipo = str(item.get("tipo", "pc")).strip() or "pc"
        if category_id == "switch":
            tipo = "switch"
            if "switch" not in modelo.lower():
                modelo = f"switch {modelo}"
        equipo = {
            "tipo": tipo,
            "modelo": modelo,
            "cantidad": cantidad,
            "propiedad": propiedad,
        }
        # Puerto ETH elegido manualmente. Formatos válidos: ETH<n> (router/switch),
        # TEL-ETH<n> / DAT-ETH<n> (switch telefonía/datos). El layout (_override_port) valida.
        puerto = str(item.get("puerto", "")).strip().upper()
        if re.match(r"^(?:(?:TEL|DAT)-)?ETH\d{1,2}$", puerto):
            equipo["puerto"] = puerto
        # Switch: a qué se conecta (router por defecto, o el 1er switch en cascada).
        if tipo == "switch":
            conectar = str(item.get("conectar", item.get("conectar_a", "router"))).strip().lower()
            if conectar in ("switch1", "switch"):
                equipo["conectar_a"] = "switch1"
        equipos.append(equipo)
    return equipos
