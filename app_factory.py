from __future__ import annotations

import os
import random
from dataclasses import dataclass

from flask import Flask, Response, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from app_context import ADMIN_USERS, PROJECT_ROOT, get_drawio_stores, security_logger
from generator.catalog_cache import CatalogCache
from generator.device_catalog import build_device_catalog
from generator.diagram_activity import DiagramActivity
from generator.download_store import DownloadStore
from generator.security_log import SecurityLog
from generator.site_directory import SiteDirectory
from generator.utils import technician_is_admin
from security_config import (
    configure_csrf,
    configure_security_logger,
    configure_session,
    configure_talisman,
    register_cache_headers,
    resolve_secret_key,
)


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

    # Seguro por defecto: la auth solo se desactiva poniendo explicitamente
    # DRAWIO_AUTH_REQUIRED=0 (uso local de desarrollo).
    app.config["AUTH_REQUIRED"] = os.environ.get("DRAWIO_AUTH_REQUIRED", "1") != "0"

    configure_session(app)
    csrf = configure_csrf(app)

    _ratelimit_uri = os.environ.get("DRAWIO_RATELIMIT_STORAGE", "memory://")
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per day", "50 per hour"],
        storage_uri=_ratelimit_uri,
        strategy="fixed-window",
    )
    if _ratelimit_uri.startswith("memory://"):
        _workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
        if _workers > 1:
            import warnings

            warnings.warn(
                f"DRAWIO_RATELIMIT_STORAGE=memory:// con WEB_CONCURRENCY={_workers}. "
                "El rate limiting no es compartido entre workers. Usa Redis en produccion.",
                stacklevel=2,
            )
        else:
            security_logger.info(
                "Rate limiting en memoria (aceptable para desarrollo o worker unico)."
            )

    static_asset_version = os.environ.get("DRAWIO_STATIC_VERSION", "20260629s")

    @app.before_request
    def _maybe_cleanup() -> None:
        if random.random() < 0.02:
            get_drawio_stores().downloads.cleanup()

    force_https = os.environ.get("DRAWIO_FORCE_HTTPS", "0") == "1"
    if os.environ.get("DRAWIO_COOKIE_SECURE", "0") == "1" or force_https:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    configure_talisman(app, force_https=force_https)
    register_cache_headers(app)

    @app.errorhandler(429)
    def _too_many_requests(_error) -> Response:
        return Response(
            "Has hecho muchas operaciones seguidas en poco tiempo. "
            "Espera un par de minutos e inténtalo de nuevo.",
            status=429,
            mimetype="text/plain; charset=utf-8",
        )

    app.config["PREVIEW_URL"] = os.environ.get("DRAWIO_PREVIEW_URL", "https://embed.diagrams.net/").rstrip("/")
    is_local_dev = os.environ.get("DRAWIO_COOKIE_SECURE", "0") != "1"
    app.config["TEMPLATES_AUTO_RELOAD"] = is_local_dev
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0 if is_local_dev else 43200

    @app.context_processor
    def inject_admin_flag() -> dict:
        tech = session.get("technician")
        return {
            "technician": tech,
            "technician_is_admin": technician_is_admin(tech, ADMIN_USERS) if tech else False,
            "static_v": static_asset_version,
        }

    from web.blueprints.admin import create_admin_blueprint
    from web.blueprints.auth import create_auth_blueprint
    from web.blueprints.diagrams import create_diagrams_blueprint
    from web.blueprints.glpi_import import create_glpi_import_blueprint
    from web.blueprints.home import create_home_blueprint
    from web.blueprints.zabbix import create_zabbix_blueprint

    app.register_blueprint(create_home_blueprint())
    app.register_blueprint(create_auth_blueprint(limiter))
    app.register_blueprint(create_diagrams_blueprint(limiter, csrf))
    app.register_blueprint(create_admin_blueprint(limiter))
    app.register_blueprint(create_glpi_import_blueprint(limiter))
    app.register_blueprint(create_zabbix_blueprint(limiter))

    return app
