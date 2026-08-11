"""Cliente de la app hacia el helper de versión RouterOS (opción A).

La app corre en un contenedor aislado sin ruta a los routers, así que delega la
consulta de versión en un helper que corre en el host y alcanza el router por el
túnel WireGuard (ver scripts/routeros_version_helper.py). Aquí solo se hace la
llamada HTTP y se decide qué template BGP corresponde.

Diseño defensivo: si el helper no está configurado o no responde, NO se rompe el
alta — se devuelve estado "desconocido" y el técnico confirma la versión a mano.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class RouterVersion:
    ok: bool
    version: str = ""
    major: int | None = None
    is_v7: bool | None = None
    board: str = ""
    error: str = ""

    @property
    def known(self) -> bool:
        return self.ok and self.is_v7 is not None


def helper_configured() -> bool:
    return bool(os.environ.get("ROUTEROS_HELPER_URL", "").strip())


def fetch_router_version(ip: str, username: str, password: str,
                         *, timeout: float | None = None) -> RouterVersion:
    base = os.environ.get("ROUTEROS_HELPER_URL", "").strip().rstrip("/")
    if not base:
        return RouterVersion(ok=False, error="Helper de versión no configurado.")
    if not (ip and username and password):
        return RouterVersion(ok=False, error="Faltan IP/usuario/contraseña del router.")

    token = os.environ.get("ROUTEROS_HELPER_TOKEN", "").strip()
    if timeout is None:
        timeout = float(os.environ.get("ROUTEROS_HELPER_TIMEOUT_S", "12"))
    body = json.dumps({"host": ip, "username": username, "password": password}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Helper-Token"] = token
    req = Request(f"{base}/routeros/version", data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        try:
            detail = json.loads(detail).get("error", detail)
        except (ValueError, json.JSONDecodeError):
            pass
        return RouterVersion(ok=False, error=f"Helper HTTP {exc.code}: {detail}")
    except URLError as exc:
        return RouterVersion(ok=False, error=f"No se pudo contactar el helper de versión: {exc.reason}")
    except (ValueError, json.JSONDecodeError):
        return RouterVersion(ok=False, error="Respuesta inválida del helper de versión.")

    if not data.get("ok"):
        return RouterVersion(ok=False, error=str(data.get("error", "El router no respondió por API.")))
    return RouterVersion(
        ok=True,
        version=str(data.get("version", "")),
        major=data.get("major"),
        is_v7=bool(data.get("is_v7")),
        board=str(data.get("board", "")),
    )
