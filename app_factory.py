from __future__ import annotations

import logging
import os
import random
import secrets
from dataclasses import dataclass
from datetime import timedelta

from flask import Flask, Response, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect

from app_context import ADMIN_USERS, PROJECT_ROOT, get_drawio_stores, security_logger
from generator.catalog_cache import CatalogCache
from generator.device_catalog import build_device_catalog
from generator.diagram_activity import DiagramActivity
from generator.download_store import DownloadStore
from generator.security_log import SecurityLog
from generator.site_directory import SiteDirectory
from generator.utils import technician_is_admin


@dataclass
class DrawioStores:
    downloads: DownloadStore
    sites: SiteDirectory
    catalog: CatalogCache
    activity: DiagramActivity
    seclog: SecurityLog


def build_drawio_stores(project_root: os.PathLike[str] | None = None) -> DrawioStores:
    root = project_root or PROJECT_ROOT
    return DrawioStores(
        downloads=DownloadStore(
            os.environ.get("DRAWIO_DOWNLOAD_DB", root / "data" / "downloads.sqlite3"),
            ttl_seconds=int(os.environ.get("DRAWIO_DOWNLOAD_TTL", "86400")),
        ),
        sites=SiteDirectory(
            os.environ.get("DRAWIO_SITE_DB", root / "data" / "sites.sqlite3")
        ),
        catalog=CatalogCache(
            os.environ.get("DRAWIO_CATALOG_DB", root / "data" / "catalog.sqlite3"),
            ttl_seconds=int(os.environ.get("DRAWIO_CATALOG_TTL", "300")),
        ),
        activity=DiagramActivity(
            os.environ.get("DRAWIO_ACTIVITY_DB", root / "data" / "activity.sqlite3")
        ),
        seclog=SecurityLog(
            os.environ.get("DRAWIO_SECLOG_DB", root / "data" / "security.sqlite3")
        ),
    )


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


def create_app(stores: DrawioStores | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"), static_folder=str(PROJECT_ROOT / "static"))
    drawio_stores = stores or build_drawio_stores()
    app.extensions["drawio_stores"] = drawio_stores
    configure_security_logger(drawio_stores.seclog)
    drawio_stores.seclog.purge_old(days=30)
    app.config["DEFAULT_LIBRARY"] = os.environ.get(
        "DRAWIO_LIBRARY_PATH",
        str(PROJECT_ROOT / "library" / "libreria_Ausarta_JUN_2026.xml"),
    )
    from generator.library_loader import validate_library_file

    for warning in validate_library_file(app.config["DEFAULT_LIBRARY"]):
        app.logger.warning(warning)
    app.config["DEVICE_CATALOG"] = build_device_catalog(app.config["DEFAULT_LIBRARY"])
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("DRAWIO_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))

    app.config["SECRET_KEY"] = resolve_secret_key()

    app.config["AUTH_REQUIRED"] = os.environ.get("DRAWIO_AUTH_REQUIRED", "0") == "1"

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("DRAWIO_COOKIE_SECURE", "0") == "1"
    app.config["SESSION_COOKIE_NAME"] = "drawio_session"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=int(os.environ.get("DRAWIO_SESSION_HOURS", "8")))

    app.config["WTF_CSRF_TIME_LIMIT"] = 14400
    app.config["WTF_CSRF_SSL_STRICT"] = app.config["SESSION_COOKIE_SECURE"]
    csrf = CSRFProtect(app)

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per day", "50 per hour"],
        storage_uri=os.environ.get("DRAWIO_RATELIMIT_STORAGE", "memory://"),
        strategy="fixed-window",
    )

    static_asset_version = os.environ.get("DRAWIO_STATIC_VERSION", "20260619b")

    @app.before_request
    def _maybe_cleanup() -> None:
        if random.random() < 0.02:
            get_drawio_stores().downloads.cleanup()

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

    force_https = os.environ.get("DRAWIO_FORCE_HTTPS", "0") == "1"
    csp = {
        "default-src": "'self'",
        "script-src": ["'self'", "embed.diagrams.net"],
        "style-src": ["'self'"],
        "img-src": ["'self'", "data:", "embed.diagrams.net"],
        "frame-src": ["'self'", "embed.diagrams.net"],
        "frame-ancestors": "'self'",
        "connect-src": ["'self'"],
    }
    use_security_headers = (
        os.environ.get("DRAWIO_ENABLE_SECURITY_HEADERS", "1") == "1"
        and os.environ.get("DRAWIO_COOKIE_SECURE", "0") == "1"
    )
    if use_security_headers:
        Talisman(
            app,
            force_https=force_https,
            strict_transport_security=force_https,
            content_security_policy=csp,
            content_security_policy_nonce_in=["script-src", "style-src"],
            frame_options=None,
            referrer_policy="strict-origin-when-cross-origin",
        )

    app.config["PREVIEW_URL"] = os.environ.get("DRAWIO_PREVIEW_URL", "https://embed.diagrams.net/").rstrip("/")
    is_local_dev = os.environ.get("DRAWIO_COOKIE_SECURE", "0") != "1"
    app.config["TEMPLATES_AUTO_RELOAD"] = is_local_dev
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0 if is_local_dev else 43200

    @app.context_processor
    def inject_admin_flag() -> dict:
        tech = session.get("technician")
        return {
            "technician_is_admin": technician_is_admin(tech, ADMIN_USERS) if tech else False,
            "static_v": static_asset_version,
        }

    from web.blueprints.admin import create_admin_blueprint
    from web.blueprints.auth import create_auth_blueprint
    from web.blueprints.diagrams import create_diagrams_blueprint
    from web.blueprints.glpi_import import create_glpi_import_blueprint

    app.register_blueprint(create_auth_blueprint(limiter))
    app.register_blueprint(create_diagrams_blueprint(limiter, csrf))
    app.register_blueprint(create_admin_blueprint())
    app.register_blueprint(create_glpi_import_blueprint(limiter))

    return app
