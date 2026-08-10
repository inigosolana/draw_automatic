"""Cliente de la app hacia el helper de credenciales Passbolt (opción B).

La app (Python, en contenedor) no puede descifrar Passbolt por sí misma, así que
delega en un sidecar que reutiliza el `passbolt-provider.js` de NOP y corre en el
host (ver scripts/credential_helper.js). Aquí solo se hace la llamada HTTP: se le
pasa la IP del router y devuelve la contraseña del usuario RouterOS.

Degradación segura: si el helper no está configurado o no responde, se devuelve
cadena vacía y el alta sigue (el técnico pega la contraseña o se completa luego).
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def helper_configured() -> bool:
    return bool(os.environ.get("PASSBOLT_HELPER_URL", "").strip())


def fetch_router_password(ip: str, *, username: str = "", timeout: float | None = None) -> str:
    base = os.environ.get("PASSBOLT_HELPER_URL", "").strip().rstrip("/")
    if not base or not ip:
        return ""
    token = os.environ.get("PASSBOLT_HELPER_TOKEN", "").strip()
    if timeout is None:
        timeout = float(os.environ.get("PASSBOLT_HELPER_TIMEOUT_S", "15"))
    body = json.dumps({"ip": ip, "username": username}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Helper-Token"] = token
    req = Request(f"{base}/credential", data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, ValueError, json.JSONDecodeError):
        return ""
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
    base = os.environ.get("PASSBOLT_HELPER_URL", "").strip().rstrip("/")
    if not base or not password:
        return {"ok": False, "error": "helper no configurado o sin contraseña"}
    token = os.environ.get("PASSBOLT_HELPER_TOKEN", "").strip()
    if timeout is None:
        timeout = float(os.environ.get("PASSBOLT_HELPER_TIMEOUT_S", "20"))
    body = json.dumps({
        "cliente": cliente, "cif": cif, "ip": ip,
        "username": username, "password": password, "folder_id": folder_id,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Helper-Token"] = token
    req = Request(f"{base}/credential/create", data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}
    return data if isinstance(data, dict) else {"ok": False, "error": "respuesta inválida"}
