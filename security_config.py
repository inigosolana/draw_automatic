from __future__ import annotations

import logging
import os
import secrets
from datetime import timedelta

from flask import Flask, Response, request
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect

from app_context import security_logger
from generator.security_log import SecurityLog

PLACEHOLDER_SECRET_KEYS = {
    "",
    "CAMBIAR_POR_UNA_CADENA_ALEATORIA_LARGA_GENERADA_CON_EL_COMANDO_ANTERIOR",
}


def _production_requires_secret_key() -> bool:
    return (
        os.environ.get("DRAWIO_AUTH_REQUIRED", "0") == "1"
        or os.environ.get("DRAWIO_COOKIE_SECURE", "0") == "1"
    )


def resolve_secret_key() -> str:
    secret_key = os.environ.get("DRAWIO_SECRET_KEY", "").strip()
    production_mode = _production_requires_secret_key()
    if secret_key in PLACEHOLDER_SECRET_KEYS:
        if production_mode:
            raise RuntimeError(
                "DRAWIO_SECRET_KEY no esta configurada o usa el valor placeholder de .env.example. "
                'Genera una clave con: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        security_logger.warning(
            "DRAWIO_SECRET_KEY no esta configurado. Generando clave temporal (las sesiones se perderan al reiniciar)."
        )
        return secrets.token_hex(32)
    return secret_key


class _SQLiteHandler(logging.Handler):
    def __init__(self, seclog: SecurityLog) -> None:
        super().__init__()
        self._seclog = seclog

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._seclog.write(record.levelname, self.format(record))
        except Exception:
            pass


def configure_security_logger(seclog: SecurityLog) -> logging.Logger:
    logger = logging.getLogger("security")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s [SECURITY] %(message)s"))
        logger.addHandler(handler)
        sqlite_handler = _SQLiteHandler(seclog)
        sqlite_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s [SECURITY] %(message)s"))
        logger.addHandler(sqlite_handler)
    return logger


def configure_session(app: Flask) -> None:
    """Configura cookies de sesión seguras."""
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("DRAWIO_COOKIE_SECURE", "0") == "1"
    app.config["SESSION_COOKIE_NAME"] = "drawio_session"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        hours=int(os.environ.get("DRAWIO_SESSION_HOURS", "8"))
    )


def configure_csrf(app: Flask) -> CSRFProtect:
    """Instala protección CSRF y devuelve la instancia."""
    app.config["WTF_CSRF_TIME_LIMIT"] = 14400
    app.config["WTF_CSRF_SSL_STRICT"] = app.config["SESSION_COOKIE_SECURE"]
    return CSRFProtect(app)


def configure_talisman(app: Flask, *, force_https: bool) -> None:
    """Aplica headers de seguridad HTTP en producción."""
    csp = {
        "default-src": "'self'",
        "script-src": ["'self'", "embed.diagrams.net", "app.diagrams.net"],
        "style-src": ["'self'", "embed.diagrams.net", "app.diagrams.net"],
        "img-src": ["'self'", "data:", "embed.diagrams.net", "app.diagrams.net"],
        "frame-src": ["'self'", "embed.diagrams.net", "app.diagrams.net"],
        "frame-ancestors": "'self'",
        "connect-src": ["'self'"],
    }
    use_security_headers = (
        os.environ.get("DRAWIO_ENABLE_SECURITY_HEADERS", "1") == "1"
        and os.environ.get("DRAWIO_COOKIE_SECURE", "0") == "1"
    )
    if not use_security_headers:
        return
    Talisman(
        app,
        force_https=force_https,
        strict_transport_security=force_https,
        content_security_policy=csp,
        content_security_policy_nonce_in=["script-src", "style-src"],
        frame_options=None,
        referrer_policy="strict-origin-when-cross-origin",
    )


def register_cache_headers(app: Flask) -> None:
    """Hook after_request para Cache-Control en HTML y assets estáticos."""

    @app.after_request
    def adjust_response_headers(response: Response) -> Response:
        if request.path.startswith("/static/"):
            response.headers.pop("Expires", None)
            response.headers.pop("Content-Security-Policy", None)
            response.headers.pop("X-Frame-Options", None)
            response.headers.pop("Referrer-Policy", None)
            response.headers.pop("Permissions-Policy", None)
        elif response.content_type and "text/html" in response.content_type:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers.pop("Expires", None)
        return response
