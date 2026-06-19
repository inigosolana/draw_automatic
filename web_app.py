from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, redirect, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect

from generator.catalog_cache import CatalogCache
from generator.diagram_activity import DiagramActivity
from generator.diagram_metadata import enrich_diagram_row
from generator.download_store import DownloadStore
from generator.glpi_client import GlpiClient, GlpiError, build_customer_catalog
from generator.security_log import SecurityLog
from generator.site_directory import SiteDirectory, apply_saved_addresses
from generator.device_catalog import build_device_catalog
from generator.safe_errors import public_error_message
from generator.utils import technician_is_admin

PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass
class DrawioStores:
    downloads: DownloadStore
    sites: SiteDirectory
    catalog: CatalogCache
    activity: DiagramActivity
    seclog: SecurityLog


def build_drawio_stores(project_root: Path | None = None) -> DrawioStores:
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


def get_drawio_stores() -> DrawioStores:
    from flask import current_app

    return current_app.extensions["drawio_stores"]


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


security_logger = logging.getLogger("security")

def _load_admin_users() -> set[str]:
    raw = os.environ.get("DRAWIO_ADMIN_USERS", "")
    if raw.strip():
        return {u.strip().lower() for u in raw.split(",") if u.strip()}
    return {
        "iñigo solana",
        "solana iñigo",
        "alberto ferez",
        "ferez alberto",
        "marcos medina",
        "medina marcos",
    }


ADMIN_USERS = _load_admin_users()

DEFAULT_HOST = os.environ.get("DRAWIO_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("DRAWIO_PORT", os.environ.get("PORT", "8000")))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

_MONTHS_ES = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
)


def _activity_technician_name(row: dict) -> str:
    return row.get("technician_name") or row.get("technician", {}).get("name", "?")


def _glpi_diagram_rows(client: GlpiClient, entity_id: int, activity: DiagramActivity) -> list[dict]:
    activity_map = activity.map_for_entity(entity_id)
    rows: list[dict] = []
    for diagram in client.list_network_diagrams(entity_id):
        diagram_id = diagram.get("id")
        if not str(diagram_id or "").isdigit():
            continue
        row = {
            "id": int(diagram_id),
            "name": diagram.get("name") or f"Diagrama #{diagram_id}",
            "description": diagram.get("shortdescription", ""),
            "state": diagram.get("plugin_archimap_graphstates_id", ""),
            "url": client.diagram_url(int(diagram_id)),
        }
        rows.append(enrich_diagram_row(row, activity_map))
    rows.sort(
        key=lambda item: activity_map.get(item["id"], {}).get("created_at", 0),
        reverse=True,
    )
    return rows


def _build_admin_chart_periods(all_rows: list[dict], now: datetime) -> dict:
    from collections import Counter

    def rows_since(days: int) -> list[dict]:
        cutoff = now - timedelta(days=days)
        return [r for r in all_rows if datetime.utcfromtimestamp(r["created_at"]) >= cutoff]

    def daily_buckets(days: int) -> tuple[list[str], list[int]]:
        labels: list[str] = []
        values: list[int] = []
        for i in range(days - 1, -1, -1):
            day = (now - timedelta(days=i)).date()
            labels.append(day.strftime("%d/%m"))
            values.append(len([
                r for r in all_rows
                if datetime.utcfromtimestamp(r["created_at"]).date() == day
            ]))
        return labels, values

    week_labels, week_values = daily_buckets(7)
    month_labels, month_values = daily_buckets(30)

    year_labels: list[str] = []
    year_values: list[int] = []
    for i in range(11, -1, -1):
        month = now.month - i
        year = now.year
        while month <= 0:
            month += 12
            year -= 1
        start = datetime(year, month, 1)
        end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        year_labels.append(f"{_MONTHS_ES[month - 1]} {str(year)[2:]}")
        year_values.append(len([
            r for r in all_rows
            if start <= datetime.utcfromtimestamp(r["created_at"]) < end
        ]))

    def period_payload(rows: list[dict], labels: list[str], values: list[int]) -> dict:
        top = Counter(_activity_technician_name(r) for r in rows).most_common(5)
        return {
            "labels": labels,
            "values": values,
            "total": len(rows),
            "top": [{"name": name, "count": count} for name, count in top],
        }

    return {
        "week": period_payload(rows_since(7), week_labels, week_values),
        "month": period_payload(rows_since(30), month_labels, month_values),
        "year": period_payload(rows_since(365), year_labels, year_values),
    }


def _build_coverage_data(
    catalog: list[dict],
    client,
    activity_rows: list[dict],
) -> dict | None:
    """Build coverage map: provinces with sites lacking a diagram.

    Returns a dict with keys:
        provinces: list of {name, technician, total_missing, clientes: [...]}
        total_sites: int
        covered_sites: int
        missing_sites: int
        error: str or None
    Returns None if GLPI is not configured.
    """
    if not client:
        return None

    from collections import Counter

    # Fetch all diagrams from GLPI (entity_ids that have diagrams)
    try:
        all_diagrams = client.list_network_diagrams()
    except GlpiError as exc:
        return {"provinces": [], "total_sites": 0, "covered_sites": 0,
                "missing_sites": 0, "error": public_error_message(str(exc), context="consulta de diagramas GLPI")}

    covered_entity_ids: set[int] = set()
    for diag in all_diagrams:
        eid = diag.get("entities_id")
        if eid and str(eid).isdigit():
            covered_entity_ids.add(int(eid))

    # Build entity_id → province_name map from catalog for activity lookup
    entity_to_province: dict[int, str] = {}
    total_sites = 0
    provinces_coverage: list[dict] = []

    for province in catalog:
        prov_name = province.get("nombre", "?")
        prov_data: dict = {"name": prov_name, "technician": "", "total_missing": 0, "clientes": []}

        for cliente in province.get("clientes", []):
            cli_name = cliente.get("nombre", "?")
            cli_data: dict = {"name": cli_name, "sedes": []}

            for sede in cliente.get("sedes", []):
                eid = sede.get("id")
                if eid is None:
                    continue
                total_sites += 1
                entity_to_province[eid] = prov_name
                if int(eid) not in covered_entity_ids:
                    cli_data["sedes"].append({
                        "name": sede.get("nombre", "?"),
                        "direccion": sede.get("direccion", ""),
                        "entity_id": int(eid),
                    })
                    prov_data["total_missing"] += 1

            if cli_data["sedes"]:
                prov_data["clientes"].append(cli_data)

        # Detect most common technician for this province from activity
        prov_technicians: Counter = Counter()
        for row in activity_rows:
            row_eid = row.get("entity_id")
            if row_eid and entity_to_province.get(row_eid) == prov_name:
                tech = row.get("technician_name") or row.get("technician_username", "?")
                if tech and tech != "?":
                    prov_technicians[tech] += 1
        if prov_technicians:
            prov_data["technician"] = prov_technicians.most_common(1)[0][0]

        if prov_data["clientes"]:
            provinces_coverage.append(prov_data)

    provinces_coverage.sort(key=lambda p: p["total_missing"], reverse=True)
    covered = total_sites - sum(p["total_missing"] for p in provinces_coverage)
    return {
        "provinces": provinces_coverage,
        "total_sites": total_sites,
        "covered_sites": covered,
        "missing_sites": sum(p["total_missing"] for p in provinces_coverage),
        "error": None,
    }


def current_technician() -> dict:
    return session.get("technician") or {"username": "local", "name": "Tecnico local"}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        from flask import current_app

        if current_app.config["AUTH_REQUIRED"] and not session.get("technician"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def load_glpi_catalog() -> tuple[list[dict], str]:
    drawio_stores = get_drawio_stores()
    cached = drawio_stores.catalog.get("glpi_customer_catalog")
    if cached is not None:
        return apply_saved_addresses(cached, drawio_stores.sites.all()), ""
    client = GlpiClient.from_environment()
    if not client:
        return [], "GLPI no esta configurado."
    try:
        catalog = build_customer_catalog(client.list_entities())
        drawio_stores.catalog.set("glpi_customer_catalog", catalog)
        return apply_saved_addresses(catalog, drawio_stores.sites.all()), ""
    except GlpiError as exc:
        security_logger.warning(f"GLPI catalog load failed: {exc} (IP: {get_remote_address()})")
        return [], public_error_message(str(exc), context="carga del catalogo GLPI")


def comms_configured() -> bool:
    from generator.comms_client import CommsClient

    return CommsClient.from_environment() is not None


def index_context(**extra):
    from flask import current_app

    glpi_customers, glpi_error = load_glpi_catalog()
    device_catalog = build_device_catalog(current_app.config["DEFAULT_LIBRARY"])
    context = {
        "device_catalog": device_catalog,
        "glpi_customers": glpi_customers,
        "glpi_error": glpi_error,
        "comms_configured": comms_configured(),
        "technician": current_technician(),
        "page_config": {
            "glpiCustomers": glpi_customers or [],
            "deviceCatalog": device_catalog,
            "importWorkOrderUrl": url_for("glpi_import.import_work_order"),
        },
    }
    context.update(extra)
    return context


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
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("DRAWIO_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))

    app.config["SECRET_KEY"] = resolve_secret_key()
    
    app.config["AUTH_REQUIRED"] = os.environ.get("DRAWIO_AUTH_REQUIRED", "0") == "1"
    
    # Security: Session configuration
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("DRAWIO_COOKIE_SECURE", "0") == "1"
    app.config["SESSION_COOKIE_NAME"] = "drawio_session"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=int(os.environ.get("DRAWIO_SESSION_HOURS", "8")))
    
    # Security: CSRF Protection
    app.config["WTF_CSRF_TIME_LIMIT"] = 14400  # 4 horas en segundos
    app.config["WTF_CSRF_SSL_STRICT"] = app.config["SESSION_COOKIE_SECURE"]
    csrf = CSRFProtect(app)
    
    # Security: Rate Limiting
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per day", "50 per hour"],
        storage_uri=os.environ.get("DRAWIO_RATELIMIT_STORAGE", "memory://"),
        strategy="fixed-window",
    )
    
    static_asset_version = os.environ.get("DRAWIO_STATIC_VERSION", "20260619a")

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

    # Security: HTTP Security Headers (Talisman) — optional (off in local dev)
    force_https = os.environ.get("DRAWIO_FORCE_HTTPS", "0") == "1"
    csp = {
        'default-src': "'self'",
        'script-src': ["'self'", "embed.diagrams.net"],
        'style-src': ["'self'", "'unsafe-inline'"],
        'img-src': ["'self'", "data:", "embed.diagrams.net"],
        'frame-src': ["'self'", "embed.diagrams.net"],
        'frame-ancestors': "'self'",
        'connect-src': ["'self'"],
    }
    # Security headers only in production (HTTPS). In local dev they block inline JS.
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
            content_security_policy_nonce_in=["script-src"],
            frame_options=None,
            referrer_policy='strict-origin-when-cross-origin',
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


if __name__ == "__main__":
    local_dev = os.environ.get("DRAWIO_COOKIE_SECURE", "0") != "1"
    print(f"Ausarta Draw.io — carpeta: {PROJECT_ROOT}")
    print(f"Local: http://127.0.0.1:{DEFAULT_PORT}/")
    create_app().run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=local_dev, use_reloader=local_dev)
