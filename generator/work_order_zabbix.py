"""Mapea una OT (ImportResult del CRM/GLPI) a los campos del alta de Zabbix.

Objetivo: que el técnico casi solo tenga que meter el nº de OT. De la OT salen
cliente, sede, dirección, tipo de conexión, proveedor y modelo de backup; de GLPI
se afina provincia/localidad/calle. Lo único que NO sale de la OT es la IP pública
(se asigna al instalar) y la contraseña (Passbolt) — esos los completa el técnico.
"""
from __future__ import annotations

import re

from .zabbix_helpers import strip_cidr

# internet_tipo de la OT -> tipo de instalación de Zabbix
_TIPO_MAP = {
    "SOLO FIBRA": "fibra",
    "FIBRA + BACK UP": "fibra_backup",
    "FIBRA + BACKUP": "fibra_backup",
    "SOLO 4G MONITORIZADO": "lte",
    "4G MONITORIZADO": "lte",
}


def _map_tipo(internet_tipo: str, router_modelo: str, backup_modelo: str) -> str:
    tipo = _TIPO_MAP.get((internet_tipo or "").strip().upper(), "")
    router = (router_modelo or "").upper()
    # CHATEAU integra fibra + backup en un solo equipo.
    if "CHATEAU" in router and tipo in ("fibra", "fibra_backup", ""):
        return "chateau"
    if not tipo:
        return "fibra_backup" if (backup_modelo or "").strip() else "fibra"
    return tipo


def _map_backup_tipo(backup_modelo: str) -> str:
    bm = (backup_modelo or "").strip().upper()
    if not bm:
        return ""
    if "TELTONIKA" in bm:
        return "TELTONIKA"
    if "KITE" in bm:
        return "KITE"
    if "WAP" in bm:
        return "WAP LTE"
    return bm


def _province_from_address(direccion: str, known_provinces: list[str]) -> str:
    """Busca una provincia conocida dentro de la cadena de dirección."""
    text = " " + re.sub(r"\s+", " ", (direccion or "")).upper() + " "
    for prov in sorted(known_provinces, key=len, reverse=True):
        if prov and f" {prov.upper()} " in text:
            return prov
    # fallback: penúltimo trozo por comas (…, Provincia, Espana)
    parts = [p.strip() for p in (direccion or "").split(",") if p.strip()]
    lowered = [p for p in parts if p.upper() not in ("ESPANA", "ESPAÑA", "SPAIN")]
    return lowered[-1] if lowered else ""


def work_order_to_prefill(result, *, glpi_customers=None) -> dict:
    """Devuelve un dict con los campos del formulario de alta prellenados.

    `result` es un ImportResult (generator.offer_mapper). `glpi_customers` es el
    catálogo GLPI (lista de provincias con clientes/sedes) para afinar
    provincia/localidad/calle por cliente.
    """
    cliente = (getattr(result, "cliente", "") or "").strip()
    sede = (getattr(result, "sede", "") or "").strip()
    direccion = (getattr(result, "direccion", "") or "").strip()
    proveedor = (getattr(result, "internet_proveedor", "") or "").strip()
    router_ip = strip_cidr((getattr(result, "router_ip", "") or "").strip())

    tipo = _map_tipo(
        getattr(result, "internet_tipo", ""),
        getattr(result, "router_modelo", ""),
        getattr(result, "backup_modelo", ""),
    )
    backup_tipo = _map_backup_tipo(getattr(result, "backup_modelo", ""))

    provincia = ""
    localidad = ""
    calle = ""
    cif = (getattr(result, "cif", "") or "").strip()
    catalog = glpi_customers or []
    known = [p.get("nombre", "") for p in catalog]

    # Afinar por GLPI: casar cliente (por CIF o nombre) y coger provincia/sede.
    def _norm(s):
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

    target = _norm(cliente)
    for prov in catalog:
        for cli in prov.get("clientes", []):
            same = (cif and cli.get("cif", "").upper() == cif.upper()) or (
                target and _norm(cli.get("nombre", "")) == target
            )
            if not same:
                continue
            provincia = prov.get("nombre", "")
            sedes = cli.get("sedes", [])
            # elegir la sede que mejor case con la de la OT, o la primera
            chosen = None
            for s in sedes:
                if sede and _norm(s.get("nombre", "")) == _norm(sede):
                    chosen = s
                    break
            chosen = chosen or (sedes[0] if sedes else None)
            if chosen:
                localidad = chosen.get("localidad", "") or ""
                calle = chosen.get("calle", "") or ""
                if not direccion:
                    direccion = chosen.get("direccion", "") or ""
            break
        if provincia:
            break

    if not provincia:
        provincia = _province_from_address(direccion, known)

    return {
        "tipo": tipo,
        "provincia": provincia,
        "cliente": cliente,
        "sede": sede,
        "localidad": localidad,
        "calle": calle,
        "proveedor": proveedor,
        "proveedor_backup": "",
        "router_ip": router_ip,
        "backup_ip": "",
        "backup_tipo": backup_tipo,
        "work_order_id": (getattr(result, "work_order_id", "") or "").strip(),
        "warnings": list(getattr(result, "warnings", []) or []),
    }
