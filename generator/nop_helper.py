"""Cliente HTTP mínimo hacia el sidecar NOP (PASSBOLT_HELPER_URL).

Varios módulos de la app (inventario de routers, servicios Yeastar, IP de backup,
credenciales Passbolt) hablan con el mismo sidecar del host con el mismo patrón:
base de env + cabecera ``X-Helper-Token`` + ``urlopen`` + parseo JSON + degradación
segura a vacío. Ese patrón vive aquí una sola vez.

Degradación segura: si el helper no está configurado o falla (red, HTTP, JSON),
se devuelve ``None`` y el llamante decide su valor vacío (lista/dict/"" según el
caso). Nunca lanza.

El helper de versión RouterOS (generator.routeros_version) NO usa esto a propósito:
usa otra variable de entorno (ROUTEROS_HELPER_URL) y necesita extraer el texto de
error del cuerpo HTTP para mostrárselo al técnico.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def helper_configured() -> bool:
    return bool(os.environ.get("PASSBOLT_HELPER_URL", "").strip())


def _base() -> str:
    return os.environ.get("PASSBOLT_HELPER_URL", "").strip().rstrip("/")


def _headers(extra: dict | None = None) -> dict:
    headers = dict(extra or {})
    token = os.environ.get("PASSBOLT_HELPER_TOKEN", "").strip()
    if token:
        headers["X-Helper-Token"] = token
    return headers


def _resolve_timeout(timeout: float | None, default: float) -> float:
    if timeout is not None:
        return timeout
    return float(os.environ.get("PASSBOLT_HELPER_TIMEOUT_S", str(default)))


def _read(req: Request, timeout: float):
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, ValueError, json.JSONDecodeError):
        return None


def helper_get(path: str, params: dict, *, timeout: float | None = None,
               timeout_default: float = 15.0):
    """GET {base}/{path}?{params} → JSON parseado, o None si no hay helper/falla."""
    base = _base()
    if not base:
        return None
    req = Request(f"{base}/{path}?{urlencode(params)}", headers=_headers(), method="GET")
    return _read(req, _resolve_timeout(timeout, timeout_default))


def helper_post(path: str, body: dict, *, timeout: float | None = None,
                timeout_default: float = 20.0):
    """POST JSON a {base}/{path} → JSON parseado, o None si no hay helper/falla."""
    base = _base()
    if not base:
        return None
    data = json.dumps(body).encode("utf-8")
    req = Request(f"{base}/{path}", data=data,
                  headers=_headers({"Content-Type": "application/json"}), method="POST")
    return _read(req, _resolve_timeout(timeout, timeout_default))
