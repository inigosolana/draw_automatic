"""Cliente de la app hacia el helper de credenciales Passbolt (opción B).

La app (Python, en contenedor) no puede descifrar Passbolt por sí misma, así que
delega en un sidecar que reutiliza el `passbolt-provider.js` de NOP y corre en el
host (ver scripts/credential_helper.js). Aquí solo se hace la llamada HTTP: se le
pasa la IP del router y devuelve la contraseña del usuario RouterOS.

Degradación segura: si el helper no está configurado o no responde, se devuelve
cadena vacía y el alta sigue (el técnico pega la contraseña o se completa luego).
"""
from __future__ import annotations

from generator.nop_helper import helper_configured, helper_post

__all__ = ["helper_configured", "fetch_router_password", "create_router_credential"]


def fetch_router_password(ip: str, *, username: str = "", timeout: float | None = None) -> str:
    if not ip:
        return ""
    data = helper_post("credential", {"ip": ip, "username": username},
                       timeout=timeout, timeout_default=15.0)
    if not isinstance(data, dict) or not data.get("ok"):
        return ""
    return str(data.get("password") or "")


def create_router_credential(
    *, cliente: str, cif: str = "", ip: str = "", username: str = "", password: str,
    folder_id: str = "", timeout: float | None = None,
) -> dict:
    """Crea el recurso en Passbolt (la contraseña la teclea el técnico) vía el sidecar.

    Devuelve {'ok': bool, ...}. Nunca lanza: si el helper no está o falla, {'ok': False,
    'error': ...} y el alta del host NO se rompe (es opt-in y no bloqueante).
    """
    if not password:
        return {"ok": False, "error": "helper no configurado o sin contraseña"}
    data = helper_post("credential/create", {
        "cliente": cliente, "cif": cif, "ip": ip,
        "username": username, "password": password, "folder_id": folder_id,
    }, timeout=timeout, timeout_default=20.0)
    if data is None:
        return {"ok": False, "error": "el helper no respondió"}
    return data if isinstance(data, dict) else {"ok": False, "error": "respuesta inválida"}
