from __future__ import annotations

import logging
import os
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING

from flask import redirect, request, session, url_for

if TYPE_CHECKING:
    from app_factory import DrawioStores

PROJECT_ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

security_logger = logging.getLogger("security")


def _load_admin_users() -> set[str]:
    raw = os.environ.get("DRAWIO_ADMIN_USERS", "").strip()
    if not raw:
        # No abortar en tiempo de import: degradar de forma controlada para no
        # romper create_app, los tests ni el uso en desarrollo local. Sin admins
        # configurados nadie obtiene privilegios de administrador (fail-safe).
        security_logger.warning(
            "DRAWIO_ADMIN_USERS no está configurado; no habrá usuarios "
            "administradores. Define una lista separada por comas en el .env."
        )
        return set()
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


ADMIN_USERS = _load_admin_users()


def _load_zabbix_users() -> set[str]:
    """Usuarios autorizados a dar de alta hosts en Zabbix (Paso 2).

    Configurable con ZABBIX_ALLOWED_USERS (lista separada por comas). Por defecto,
    solo Iñigo Solana, Alberto Ferez y Marcos Medina. Se incluyen tanto la forma
    usuario.punto como nombre-con-espacio porque el login puede devolver cualquiera.
    """
    raw = os.environ.get("ZABBIX_ALLOWED_USERS", "").strip()
    if raw:
        return {u.strip() for u in raw.split(",") if u.strip()}
    return {
        "inigo.solana", "inigo solana",
        "alberto.ferez", "alberto ferez",
        "marcos.medina", "marcos medina",
    }


ZABBIX_ALLOWED_USERS = _load_zabbix_users()


def technician_can_use_zabbix(technician: dict | None = None) -> bool:
    """¿El técnico puede usar el alta de Zabbix? Bypass en dev (sin auth)."""
    from flask import current_app

    try:
        if not current_app.config.get("AUTH_REQUIRED", True):
            return True
    except RuntimeError:
        pass  # fuera de contexto de app: se decide solo por la lista
    from generator.utils import technician_is_admin

    tech = technician if technician is not None else current_technician()
    return technician_is_admin(tech, ZABBIX_ALLOWED_USERS)


DEFAULT_HOST = os.environ.get("DRAWIO_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("DRAWIO_PORT", os.environ.get("PORT", "8000")))


def get_drawio_stores() -> DrawioStores:
    from flask import current_app

    return current_app.extensions["drawio_stores"]


def current_technician() -> dict:
    return session.get("technician") or {"username": "local", "name": "Tecnico local"}


def technician_label(technician: dict | None = None) -> str:
    """Nombre legible del tecnico para auditoria: name > username > 'desconocido'."""
    technician = technician if technician is not None else current_technician()
    return technician.get("name") or technician.get("username") or "desconocido"


def can_access_pending(payload: dict) -> bool:
    """El diagrama pendiente (token) solo es accesible por el técnico que lo creó
    o por un admin. Evita que otro usuario con el token previsualice/confirme/
    descargue diagramas ajenos."""
    from generator.utils import technician_is_admin

    owner = (payload.get("technician") or {}).get("username")
    if not owner:
        return True  # payloads antiguos sin técnico: no bloquear
    tech = current_technician()
    return owner == tech.get("username") or technician_is_admin(tech, ADMIN_USERS)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        from flask import current_app

        if current_app.config["AUTH_REQUIRED"] and not session.get("technician"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped
