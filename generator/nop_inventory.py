"""Consulta el inventario de routers de NOP (IP + versión) por cliente/CIF.

Se apoya en el mismo sidecar del host (PASSBOLT_HELPER_URL) que ya lee los datos
de NOP; su endpoint /routers devuelve, para un cliente, sus routers de fibra con
IP y versión. Sirve para autorrellenar IP y versión en el alta de Zabbix a partir
de la OT, sin que el técnico los teclee.

Degradación segura: si no hay helper o no responde, devuelve lista/dict vacíos.
"""
from __future__ import annotations

from generator.nop_helper import helper_configured, helper_get


def inventory_configured() -> bool:
    return helper_configured()


def fetch_client_routers(cif: str = "", cliente: str = "", *, timeout: float | None = None) -> list[dict]:
    if not (cif or cliente):
        return []
    data = helper_get("routers", {"cif": cif or "", "cliente": cliente or ""},
                      timeout=timeout, timeout_default=15.0)
    if not isinstance(data, dict) or not data.get("ok"):
        return []
    routers = data.get("routers")
    return routers if isinstance(routers, list) else []


def fetch_client_services(cif: str = "", cliente: str = "", *, timeout: float | None = None) -> dict:
    """Servicios activos del cliente en Yeastar: {proveedor, tiene_backup, backup_proveedor}.

    Vacío si no hay helper o no responde.
    """
    if not (cif or cliente):
        return {}
    data = helper_get("services", {"cif": cif or "", "cliente": cliente or ""},
                      timeout=timeout, timeout_default=15.0)
    if not isinstance(data, dict) or not data.get("ok"):
        return {}
    return {
        "proveedor": str(data.get("proveedor") or ""),
        "tiene_backup": bool(data.get("tiene_backup")),
        "backup_proveedor": str(data.get("backup_proveedor") or ""),
    }


def fetch_backup_ip(cliente: str = "", *, timeout: float | None = None) -> str:
    """IP privada del backup (del router de túneles). Vacío si no hay o no responde."""
    if not cliente:
        return ""
    data = helper_get("tunnel-ip", {"cliente": cliente}, timeout=timeout, timeout_default=20.0)
    matches = data.get("matches") if isinstance(data, dict) else None
    if isinstance(matches, list) and matches:
        return str(matches[0].get("ip") or "")
    return ""
