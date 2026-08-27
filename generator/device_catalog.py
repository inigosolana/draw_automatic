from __future__ import annotations

import re


# Lista CURADA de switches ofrecidos en el desplegable. Un modelo real por
# tipo, con su nº de puertos fijo. El `value` es el nombre que se guarda (y con
# el que se busca el icono en la librería); el `label` es lo que ve el técnico.
# poe=True marca los PoE. Sin librería-basura: solo estos.
SWITCH_CATALOG: list[dict] = [
    {"value": "TP-Link TL-SG1005D", "label": "TP-Link 5 puertos (TL-SG1005D)", "ports": 5, "poe": False},
    {"value": "TP-Link TL-SG1008D", "label": "TP-Link 8 puertos (TL-SG1008D)", "ports": 8, "poe": False},
    {"value": "TP-Link 16P", "label": "TP-Link 16 puertos (TL-SG1016D)", "ports": 16, "poe": False},
    {"value": "TP-Link TL-SG1005P", "label": "TP-Link PoE 5 puertos (TL-SG1005P)", "ports": 5, "poe": True},
    {"value": "TP-Link TL-SG1008P", "label": "TP-Link PoE 8 puertos (TL-SG1008P)", "ports": 8, "poe": True},
    {"value": "Switch 24 puertos", "label": "Switch 24 puertos", "ports": 24, "poe": False},
    {"value": "Switch 48 puertos", "label": "Switch 48 puertos", "ports": 48, "poe": False},
]

# Compat: lista de nombres (usada por alias y tests).
SWITCH_MODELS: list[str] = [d["value"] for d in SWITCH_CATALOG]

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
        # Altavoz de megafonia SIP: se alimenta y conecta por PoE, asi que en el
        # diagrama cuelga del switch como el resto de dispositivos de red.
        "id": "megafonia",
        "label": "Altavoz / megafonía SIP",
        "tipo": "otro",
        "models": ["Grandstream GSC3506"],
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


def build_device_catalog(library_path: str | None = None) -> list[dict]:
    # Lista de switches CURADA (SWITCH_CATALOG): un modelo por tipo, sin la
    # basura/duplicados que traía la librería. Puertos fijos por entrada.
    categories: list[dict] = []
    for category in DEVICE_CATEGORIES:
        entry = dict(category)
        if entry["id"] == "switch":
            entry["models"] = [
                {"value": d["value"], "label": d["label"], "ports": d["ports"],
                 "detected": True, "poe": d.get("poe", False)}
                for d in SWITCH_CATALOG
            ]
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
        if tipo == "switch":
            # El "puerto" de un switch indica a QUÉ se conecta (cascada):
            #   TEL-ETHn -> cuelga del Switch 1 (telefonía)
            #   DAT-ETHn -> cuelga del Switch 2 (datos)
            #   ETHn / Auto -> router principal (por defecto)
            # El puerto concreto del switch padre se guarda en conectar_puerto
            # para etiquetar el cable de cascada. El switch no usa override de
            # puerto de dispositivo (se coloca en _place_switch).
            casc = re.match(r"^(TEL|DAT)-ETH(\d{1,2})$", puerto)
            if casc:
                equipo["conectar_a"] = "switch1" if casc.group(1) == "TEL" else "switch2"
                equipo["conectar_puerto"] = f"ETH{casc.group(2)}"
            elif re.match(r"^ETH\d{1,2}$", puerto):
                # Puerto del router elegido explícitamente para el switch.
                equipo["conectar_puerto_router"] = puerto
        elif re.match(r"^(?:(?:TEL|DAT)-)?ETH\d{1,2}$", puerto):
            equipo["puerto"] = puerto
        # Piso/planta asignado (para dibujar el contenedor de piso en el diagrama).
        piso = str(item.get("piso", "")).strip()
        if piso:
            equipo["piso"] = piso
        equipos.append(equipo)
    return equipos
