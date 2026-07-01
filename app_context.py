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
        raise RuntimeError(
            "DRAWIO_ADMIN_USERS no está configurado. "
            "Define una lista separada por comas en el fichero .env."
        )
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


ADMIN_USERS = _load_admin_users()

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
