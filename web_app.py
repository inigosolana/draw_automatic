from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException
from flask import Flask, Response, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect

from generator.catalog_cache import CatalogCache
from generator.diagram_activity import DiagramActivity
from generator.diagram_metadata import (
    build_diagram_description,
    enrich_diagram_row,
    format_activity_timestamp,
    unique_diagram_name,
)
from generator.download_store import DownloadStore
from generator.comms_client import CommsClient, CommsError, import_products_text
from generator.work_order_text_parser import parse_work_order_paste
from generator.safe_errors import public_error_message
from generator.glpi_merge import merge_import_with_glpi
from generator.glpi_client import GlpiClient, GlpiError, build_customer_catalog
from generator.knowledge_base import learn_from_drawio
from generator.security_log import SecurityLog
from generator.site_directory import SiteDirectory, apply_saved_addresses
from generator.device_catalog import build_device_catalog
from generator.utils import is_safe_redirect, positive_integer, technician_is_admin
from generator.web_adapter import build_drawio_from_data, form_to_data, form_to_structured_data

PROJECT_ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

DOWNLOADS = DownloadStore(
    os.environ.get("DRAWIO_DOWNLOAD_DB", PROJECT_ROOT / "data" / "downloads.sqlite3"),
    ttl_seconds=int(os.environ.get("DRAWIO_DOWNLOAD_TTL", "86400")),
)
SITES = SiteDirectory(
    os.environ.get("DRAWIO_SITE_DB", PROJECT_ROOT / "data" / "sites.sqlite3")
)
CATALOG = CatalogCache(
    os.environ.get("DRAWIO_CATALOG_DB", PROJECT_ROOT / "data" / "catalog.sqlite3"),
    ttl_seconds=int(os.environ.get("DRAWIO_CATALOG_TTL", "300")),
)
ACTIVITY = DiagramActivity(
    os.environ.get("DRAWIO_ACTIVITY_DB", PROJECT_ROOT / "data" / "activity.sqlite3")
)
SECLOG = SecurityLog(
    os.environ.get("DRAWIO_SECLOG_DB", PROJECT_ROOT / "data" / "security.sqlite3")
)
DEFAULT_HOST = os.environ.get("DRAWIO_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("DRAWIO_PORT", os.environ.get("PORT", "8000")))
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
    def emit(self, record: logging.LogRecord) -> None:
        try:
            SECLOG.write(record.levelname, self.format(record))
        except Exception:
            pass


# Configure security logging
security_logger = logging.getLogger("security")
security_logger.setLevel(logging.INFO)
if not security_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s [SECURITY] %(message)s"))
    security_logger.addHandler(handler)
    sqlite_handler = _SQLiteHandler()
    sqlite_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s [SECURITY] %(message)s"))
    security_logger.addHandler(sqlite_handler)

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

_MONTHS_ES = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
)


def _activity_technician_name(row: dict) -> str:
    return row.get("technician_name") or row.get("technician", {}).get("name", "?")


def _glpi_diagram_rows(client: GlpiClient, entity_id: int) -> list[dict]:
    activity_map = ACTIVITY.map_for_entity(entity_id)
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


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"), static_folder=str(PROJECT_ROOT / "static"))
    SECLOG.purge_old(days=30)
    app.config["DEFAULT_LIBRARY"] = os.environ.get(
        "DRAWIO_LIBRARY_PATH",
        str(PROJECT_ROOT / "library" / "libreria_Ausarta_JUN_2026.xml"),
    )
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
    
    static_asset_version = os.environ.get("DRAWIO_STATIC_VERSION", "20260618f")

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
        'script-src': ["'self'", "'unsafe-inline'", "embed.diagrams.net"],
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
            frame_options=None,
            referrer_policy='strict-origin-when-cross-origin',
        )
    
    app.config["PREVIEW_URL"] = os.environ.get("DRAWIO_PREVIEW_URL", "https://embed.diagrams.net/").rstrip("/")
    is_local_dev = os.environ.get("DRAWIO_COOKIE_SECURE", "0") != "1"
    app.config["TEMPLATES_AUTO_RELOAD"] = is_local_dev
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0 if is_local_dev else 43200

    def current_technician() -> dict:
        return session.get("technician") or {"username": "local", "name": "Tecnico local"}

    @app.context_processor
    def inject_admin_flag() -> dict:
        tech = session.get("technician")
        return {
            "technician_is_admin": technician_is_admin(tech, ADMIN_USERS) if tech else False,
            "static_v": static_asset_version,
        }

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if app.config["AUTH_REQUIRED"] and not session.get("technician"):
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)

        return wrapped

    def load_glpi_catalog() -> tuple[list[dict], str]:
        cached = CATALOG.get("glpi_customer_catalog")
        if cached is not None:
            return apply_saved_addresses(cached, SITES.all()), ""
        client = GlpiClient.from_environment()
        if not client:
            return [], "GLPI no esta configurado."
        try:
            catalog = build_customer_catalog(client.list_entities())
            CATALOG.set("glpi_customer_catalog", catalog)
            return apply_saved_addresses(catalog, SITES.all()), ""
        except GlpiError as exc:
            security_logger.warning(f"GLPI catalog load failed: {exc} (IP: {get_remote_address()})")
            return [], public_error_message(str(exc), context="carga del catalogo GLPI")

    @app.route("/login", methods=["GET", "POST"])
    @limiter.limit("10 per minute")
    def login() -> str:
        error = ""
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            client_ip = get_remote_address()
            
            client = GlpiClient.from_environment()
            if not client:
                error = "El acceso no esta disponible en este momento."
                security_logger.warning(f"Login attempt failed: GLPI not configured (IP: {client_ip})")
            elif not username or not password:
                error = "Introduce usuario y clave de acceso."
                security_logger.warning(f"Login attempt failed: empty credentials (IP: {client_ip})")
            else:
                try:
                    session.clear()
                    session["technician"] = client.authenticate_user(username, password)
                    session.permanent = True
                    security_logger.info(f"Login successful: user={username}, IP={client_ip}")
                    next_url = request.args.get("next", "")
                    return redirect(next_url if is_safe_redirect(next_url) else url_for("index"))
                except GlpiError:
                    error = "Usuario o clave incorrectos."
                    security_logger.warning(f"Login attempt failed: invalid credentials for user={username}, IP={client_ip}")
        return render_template("login.html", error=error)

    @app.get("/logout")
    def logout_get() -> Response:
        return redirect(url_for("login"))

    @app.post("/logout")
    def logout() -> Response:
        username = session.get("technician", {}).get("username", "unknown")
        client_ip = get_remote_address()
        session.clear()
        security_logger.info(f"Logout: user={username}, IP={client_ip}")
        return redirect(url_for("login"))

    def comms_configured() -> bool:
        return CommsClient.from_environment() is not None

    def index_context(**extra):
        glpi_customers, glpi_error = load_glpi_catalog()
        context = {
            "device_catalog": build_device_catalog(app.config["DEFAULT_LIBRARY"]),
            "glpi_customers": glpi_customers,
            "glpi_error": glpi_error,
            "comms_configured": comms_configured(),
            "technician": current_technician(),
        }
        context.update(extra)
        return context

    @app.get("/")
    @login_required
    def index() -> str:
        return render_template(
            "index.html",
            **index_context(form_data={"library_path": app.config["DEFAULT_LIBRARY"]}),
        )

    @app.get("/health")
    @csrf.exempt
    @limiter.limit("30 per minute")
    def health() -> Response:
        return Response(
            json.dumps({"status": "ok"}),
            mimetype="application/json",
        )

    @app.get("/diagrams")
    @login_required
    def diagrams() -> str:
        glpi_customers, glpi_error = load_glpi_catalog()
        selected_entity = request.args.get("entity_id", "").strip()
        diagram_rows: list[dict] = []
        if selected_entity:
            try:
                entity_id = positive_integer(selected_entity, "entity_id")
                client = GlpiClient.from_environment()
                if not client:
                    raise GlpiError("GLPI no esta configurado.")
                diagram_rows = _glpi_diagram_rows(client, entity_id)
            except (ValueError, GlpiError) as exc:
                glpi_error = public_error_message(str(exc), context="consulta de diagramas GLPI")
        return render_template(
            "diagrams.html",
            glpi_customers=glpi_customers,
            glpi_error=glpi_error,
            diagrams=diagram_rows,
            selected_entity=selected_entity,
            technician=current_technician(),
        )

    @app.get("/my-diagrams")
    @login_required
    def my_diagrams() -> str:
        technician = current_technician()
        username = technician.get("username") or technician.get("name") or "local"
        client = GlpiClient.from_environment()
        rows = []
        for item in ACTIVITY.list_for_technician(username):
            item["created_label"] = format_activity_timestamp(item["created_at"])
            item["technician"] = item.get("technician_name") or username
            item["url"] = client.diagram_url(item["diagram_id"]) if client else ""
            rows.append(item)
        return render_template(
            "my_diagrams.html",
            diagrams=rows,
            technician=technician,
        )

    @app.get("/admin")
    @login_required
    def admin_dashboard() -> str:
        technician = current_technician()
        if not technician_is_admin(technician, ADMIN_USERS):
            tech_name = (
                technician.get("name") or technician.get("username") or ""
            ).strip().lower()
            security_logger.warning(
                f"Acceso denegado a /admin: user={tech_name}, IP={get_remote_address()}"
            )
            return Response("Acceso restringido.", status=403, mimetype="text/plain; charset=utf-8")

        from collections import Counter

        now = datetime.utcnow()
        all_rows = ACTIVITY.list_all() if hasattr(ACTIVITY, "list_all") else []
        today = [r for r in all_rows if datetime.utcfromtimestamp(r["created_at"]).date() == now.date()]
        week = [r for r in all_rows if datetime.utcfromtimestamp(r["created_at"]) >= now - timedelta(days=7)]
        month = [r for r in all_rows if datetime.utcfromtimestamp(r["created_at"]) >= now - timedelta(days=30)]
        chart_periods = _build_admin_chart_periods(all_rows, now)

        # Coverage: provinces/clients/sites without diagrams
        coverage_data = None
        try:
            glpi_client = GlpiClient.from_environment()
            if glpi_client:
                catalog_for_coverage, _ = load_glpi_catalog()
                if catalog_for_coverage:
                    cached = CATALOG.get("admin_coverage")
                    if cached is not None:
                        coverage_data = cached
                    else:
                        coverage_data = _build_coverage_data(catalog_for_coverage, glpi_client, all_rows)
                        CATALOG.set("admin_coverage", coverage_data)
        except Exception:
            pass

        import re as _re
        recent_events = SECLOG.recent(limit=200)
        warn_count = 0
        for ev in recent_events:
            ev["ts_label"] = datetime.fromtimestamp(ev["ts"]).strftime("%d/%m/%Y %H:%M:%S")
            clean = _re.sub(
                r'^\[[\d\-: ,]+\]\s*(WARNING|INFO|ERROR|CRITICAL)\s*\[SECURITY\]\s*',
                '',
                ev.get("message", ""),
            )
            ev["message_clean"] = clean or ev.get("message", "")
            if ev.get("level") in ("WARNING", "ERROR", "CRITICAL"):
                warn_count += 1
        return render_template(
            "admin.html",
            total_today=len(today),
            total_week=len(week),
            total_month=len(month),
            total_all=len(all_rows),
            recent_events=recent_events,
            technician=technician,
            warn_count=warn_count,
            chart_periods=chart_periods,
            now_label=now.strftime("%d/%m/%Y %H:%M") + " UTC",
            coverage_data=coverage_data,
        )

    @app.route("/upload-draw", methods=["GET", "POST"])
    @login_required
    @limiter.limit("20 per hour")
    def upload_draw() -> str:
        glpi_customers, glpi_error = load_glpi_catalog()
        upload_error = ""
        upload_results: list[dict] = []
        upload_errors: list[str] = []
        if request.method == "POST":
            entity_id = request.form.get("glpi_entity_id", "").strip()
            client_name = request.form.get("glpi_cliente", "").strip()
            site_name = request.form.get("glpi_sede", "").strip()
            uploaded_files = request.files.getlist("drawio_files")
            if not uploaded_files or not uploaded_files[0].filename:
                legacy_file = request.files.get("drawio_file")
                uploaded_files = [legacy_file] if legacy_file and legacy_file.filename else []
            client_ip = get_remote_address()
            technician_name = current_technician().get("name", "unknown")

            if not entity_id:
                upload_error = "Selecciona una sede de GLPI."
            elif not uploaded_files:
                upload_error = "Selecciona uno o varios archivos .drawio."
            else:
                try:
                    validated_entity_id = positive_integer(entity_id, "glpi_entity_id")
                    client = GlpiClient.from_environment()
                    if not client:
                        raise GlpiError("GLPI no esta configurado.")
                    existing_diagrams = client.list_network_diagrams(validated_entity_id)
                    technician = current_technician()
                    for uploaded_file in uploaded_files:
                        if not uploaded_file or not uploaded_file.filename:
                            continue
                        if not uploaded_file.filename.lower().endswith((".drawio", ".xml")):
                            upload_errors.append(
                                f"{uploaded_file.filename}: extension no valida (.drawio o .xml)."
                            )
                            security_logger.warning(
                                f"Upload attempt with invalid file type: {uploaded_file.filename}, "
                                f"user={technician_name}, IP={client_ip}"
                            )
                            continue
                        try:
                            raw = uploaded_file.read()
                            xml = raw.decode("utf-8-sig")
                            root = DefusedET.fromstring(xml)
                            if root.tag != "mxfile":
                                raise ValueError("El documento no contiene un mxfile de Draw.io.")
                            diagram_name = unique_diagram_name(
                                Path(uploaded_file.filename).stem,
                                existing_diagrams,
                            )
                            diagram_id = client.create_network_diagram(
                                entity_id=validated_entity_id,
                                name=diagram_name,
                                description=build_diagram_description(
                                    client_name=client_name,
                                    site_name=site_name,
                                    technician=technician,
                                    source="Archivo antiguo",
                                    filename=uploaded_file.filename,
                                ),
                                graph_xml=xml,
                            )
                            ACTIVITY.add(
                                diagram_id=diagram_id,
                                entity_id=validated_entity_id,
                                diagram_name=diagram_name,
                                client_name=client_name,
                                site_name=site_name,
                                technician=technician,
                                source="Archivo antiguo",
                            )
                            learned_models = learn_from_drawio(xml, uploaded_file.filename)
                            created = {
                                "id": diagram_id,
                                "url": client.diagram_url(diagram_id),
                                "filename": uploaded_file.filename,
                                "name": diagram_name,
                                "cliente": client_name,
                                "sede": site_name,
                                "technician": technician.get("name") or technician.get("username") or "",
                                "created_label": format_activity_timestamp(datetime.now().timestamp()),
                                "learned_models": learned_models,
                            }
                            upload_results.append(created)
                            existing_diagrams.append({"id": diagram_id, "name": diagram_name})
                            security_logger.info(
                                f"File uploaded successfully: diagram_id={diagram_id}, "
                                f"file={uploaded_file.filename}, user={technician_name}, IP={client_ip}"
                            )
                        except (UnicodeDecodeError, DefusedET.ParseError, DefusedXmlException, ValueError, GlpiError) as exc:
                            upload_errors.append(
                                f"{uploaded_file.filename}: {public_error_message(str(exc), context='subida del diagrama')}"
                            )
                            security_logger.warning(
                                f"Upload failed: {exc}, file={uploaded_file.filename}, "
                                f"user={technician_name}, IP={client_ip}"
                            )
                    if not upload_results and not upload_error:
                        upload_error = (
                            upload_errors[0]
                            if len(upload_errors) == 1
                            else "No se ha podido subir ningun archivo."
                        )
                except (ValueError, GlpiError) as exc:
                    upload_error = public_error_message(str(exc), context="subida del diagrama")
                    security_logger.warning(f"Upload failed: {exc}, user={technician_name}, IP={client_ip}")
        return render_template(
            "upload_draw.html",
            glpi_customers=glpi_customers,
            glpi_error=glpi_error,
            upload_error=upload_error,
            upload_errors=upload_errors,
            upload_results=upload_results,
            technician=current_technician(),
        )

    @app.post("/generate")
    @login_required
    @limiter.limit("30 per hour")
    def generate() -> str:
        form_data = request.form.to_dict()
        form_data.setdefault("library_path", app.config["DEFAULT_LIBRARY"])
        try:
            data = form_to_data(form_data)
            structured_data = form_to_structured_data(form_data)
            generated = build_drawio_from_data(data, form_data.get("library_path", app.config["DEFAULT_LIBRARY"]))
        except FileNotFoundError:
            return render_template(
                "index.html",
                **index_context(
                    form_data=form_data,
                    errors=["No se ha encontrado la libreria. Revisa la ruta."],
                    preview=None,
                ),
            ), 400
        except ValueError as exc:
            errors = [line for line in str(exc).splitlines() if line.strip()]
            return render_template(
                "index.html",
                **index_context(form_data=form_data, errors=errors, preview=None),
            ), 400

        glpi_entity_id = form_data.get("glpi_entity_id", "").strip()
        if glpi_entity_id:
            try:
                glpi_entity_id = positive_integer(glpi_entity_id, "glpi_entity_id")
            except ValueError as exc:
                return render_template(
                    "index.html",
                    **index_context(form_data=form_data, errors=[str(exc)], preview=None),
                ), 400
            technician = current_technician()
            SITES.set(
                glpi_entity_id,
                generated.data.get("direccion", ""),
                technician.get("name") or technician.get("username") or "desconocido",
            )
        token = uuid.uuid4().hex
        existing_diagrams: list[dict] = []
        glpi_client = GlpiClient.from_environment()
        if glpi_entity_id and glpi_client:
            try:
                existing_diagrams = _glpi_diagram_rows(glpi_client, glpi_entity_id)
            except GlpiError:
                existing_diagrams = []
        technician = current_technician()
        DOWNLOADS[token] = {
            "filename": generated.filename,
            "xml": generated.result.xml,
            "entity_id": glpi_entity_id,
            "cliente": generated.data.get("cliente", ""),
            "sede": generated.data.get("sede", ""),
            "uploaded": False,
            "technician": technician,
            "existing_diagram_ids": [
                int(item["id"]) for item in existing_diagrams if str(item.get("id", "")).isdigit()
            ],
        }
        preview = {
            "cliente": generated.data.get("cliente", ""),
            "sede": generated.data.get("sede", ""),
            "direccion": generated.data.get("direccion", ""),
            "template": generated.data.get("template", ""),
            "total_equipment": generated.total_equipment,
            "warnings": generated.result.warnings,
            "download_url": url_for("download", token=token),
            "filename": generated.filename,
            "structured_json": json.dumps(structured_data, ensure_ascii=False, indent=2),
            "glpi_diagram_id": None,
            "glpi_diagram_url": "",
            "glpi_upload_error": "",
            "confirm_url": url_for("confirm_glpi", token=token) if glpi_entity_id else "",
            "preview_url": url_for("preview_drawio", token=token),
            "technician": technician,
            "existing_diagrams": existing_diagrams,
        }
        return render_template(
            "index.html",
            **index_context(form_data=form_data, preview=preview, errors=[]),
        )

    @app.get("/download/<token>")
    @login_required
    def download(token: str) -> Response:
        payload = DOWNLOADS.get(token)
        if not payload:
            return Response("Archivo no encontrado.", status=404, mimetype="text/plain; charset=utf-8")
        if payload.get("uploaded"):
            return Response(
                "El diagrama ya fue publicado en GLPI y no puede descargarse de nuevo.",
                status=410,
                mimetype="text/plain; charset=utf-8",
            )
        return Response(
            payload["xml"],
            mimetype="application/xml; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{payload["filename"]}"'},
        )

    @app.get("/preview/<token>")
    @login_required
    def preview_drawio(token: str) -> str:
        payload = DOWNLOADS.get(token)
        if not payload:
            return Response("Diagrama pendiente no encontrado.", status=404)
        return render_template(
            "preview.html",
            token=token,
            filename=payload["filename"],
            xml_json=json.dumps(payload["xml"]),
            preview_base_url=app.config["PREVIEW_URL"],
        )

    @app.post("/api/import-work-order")
    @login_required
    @limiter.limit("30 per hour")
    def import_work_order() -> Response:
        if request.content_length and request.content_length > 64 * 1024:
            return Response(
                json.dumps({"error": "El payload es demasiado grande (máx. 64 KB)."}, ensure_ascii=False),
                status=413,
                mimetype="application/json; charset=utf-8",
            )
        payload = request.get_json(silent=True) or {}
        pasted_text = str(
            payload.get("pasted_text")
            or payload.get("work_order_text")
            or request.form.get("pasted_text")
            or ""
        ).strip()
        url = str(payload.get("url") or request.form.get("url") or "").strip()
        products_text = str(payload.get("products_text") or request.form.get("products_text") or "").strip()
        try:
            if pasted_text:
                result = parse_work_order_paste(pasted_text)
            elif products_text and not url:
                result = import_products_text(products_text)
            elif url:
                client = CommsClient.from_environment()
                if not client:
                    raise CommsError(
                        "AusartaConecta no esta configurado. Pega el texto copiado de la OT."
                    )
                result = client.import_work_order(url)
            else:
                raise CommsError("Pega el texto copiado de la orden de trabajo o un enlace de comms.")
        except (CommsError, ValueError) as exc:
            security_logger.warning(f"Work order import failed: {exc} (IP: {get_remote_address()})")
            return Response(
                json.dumps(
                    {"error": public_error_message(str(exc), context="importacion de la oferta")},
                    ensure_ascii=False,
                ),
                status=400,
                mimetype="application/json; charset=utf-8",
            )

        glpi_customers, glpi_error = load_glpi_catalog()
        imported = {
            "cliente": result.cliente,
            "cif": result.cif,
            "sede": result.sede,
            "direccion": result.direccion,
        }
        glpi_merge = merge_import_with_glpi(imported, glpi_customers)
        response_warnings = list(result.warnings)
        for correction in glpi_merge.get("corrections") or []:
            response_warnings.append(
                f"{correction['label']} corregido ({correction['source']}): "
                f"«{correction['before']}» → «{correction['after']}»"
            )

        security_logger.info(
            f"Work order imported: id={result.work_order_id or 'text'}, "
            f"products={len(result.terminals) + len(result.devices_json)}, "
            f"glpi_matched={glpi_merge.get('matched')}, IP={get_remote_address()}"
        )
        return Response(
            json.dumps(
                {
                    "work_order_id": result.work_order_id,
                    "cliente": glpi_merge.get("cliente") or result.cliente,
                    "cif": glpi_merge.get("cif") or result.cif,
                    "sede": glpi_merge.get("sede") or result.sede,
                    "direccion": glpi_merge.get("direccion") or result.direccion,
                    "glpi_entity_id": glpi_merge.get("glpi_entity_id") or "",
                    "glpi_matched": glpi_merge.get("matched", False),
                    "glpi_confidence": glpi_merge.get("confidence", "none"),
                    "glpi_message": glpi_merge.get("message") or public_error_message(glpi_error, context="sincronizacion GLPI"),
                    "glpi_corrections": glpi_merge.get("corrections") or [],
                    "glpi_suggestions": glpi_merge.get("suggestions") or [],
                    "internet_tipo": result.internet_tipo,
                    "internet_proveedor": result.internet_proveedor,
                    "internet_velocidad": result.internet_velocidad,
                    "ont_modelo": result.ont_modelo,
                    "router_modelo": result.router_modelo,
                    "backup_modelo": result.backup_modelo,
                    "router_ip": result.router_ip,
                    "devices_json": result.devices_json,
                    "terminals": result.terminals,
                    "warnings": response_warnings,
                },
                ensure_ascii=False,
            ),
            mimetype="application/json; charset=utf-8",
        )

    @app.post("/confirm-glpi/<token>")
    @login_required
    def confirm_glpi(token: str) -> str:
        payload = DOWNLOADS.get(token)
        if not payload:
            return Response("Diagrama pendiente no encontrado.", status=404, mimetype="text/plain; charset=utf-8")
        if payload["uploaded"]:
            return Response("El diagrama ya fue subido a GLPI.", status=409, mimetype="text/plain; charset=utf-8")
        client = GlpiClient.from_environment()
        if not client:
            return Response("GLPI no esta configurado.", status=503, mimetype="text/plain; charset=utf-8")
        try:
            entity_id = positive_integer(payload.get("entity_id"), "entity_id")
            technician = payload.get("technician") or current_technician()
            existing = client.list_network_diagrams(entity_id)
            allow_duplicate = request.form.get("allow_duplicate") == "1"
            if existing and not allow_duplicate:
                return Response(
                    "Esta sede ya tiene un diagrama en GLPI. Confirma de nuevo para publicar otro.",
                    status=409,
                    mimetype="text/plain; charset=utf-8",
                )
            diagram_name = unique_diagram_name(
                f"{payload['cliente']} - {payload['sede']}",
                existing,
            )
            diagram_id = client.create_network_diagram(
                entity_id=entity_id,
                name=diagram_name,
                description=build_diagram_description(
                    client_name=payload["cliente"],
                    site_name=payload["sede"],
                    technician=technician,
                    source="Generado",
                    filename=payload.get("filename", ""),
                ),
                graph_xml=payload["xml"],
            )
            ACTIVITY.add(
                diagram_id=diagram_id,
                entity_id=entity_id,
                diagram_name=diagram_name,
                client_name=payload["cliente"],
                site_name=payload["sede"],
                technician=technician,
                source="Generado",
            )
        except ValueError as exc:
            return Response(public_error_message(str(exc), context="publicacion en GLPI"), status=400, mimetype="text/plain; charset=utf-8")
        except GlpiError as exc:
            security_logger.warning(f"GLPI confirm failed: {exc} (IP: {get_remote_address()})")
            return Response(public_error_message(str(exc), context="publicacion en GLPI"), status=502, mimetype="text/plain; charset=utf-8")
        DOWNLOADS.update_payload(token, uploaded=True)
        return Response(
            json.dumps({"id": diagram_id, "url": client.diagram_url(diagram_id)}),
            mimetype="application/json",
        )

    return app


if __name__ == "__main__":
    local_dev = os.environ.get("DRAWIO_COOKIE_SECURE", "0") != "1"
    print(f"Ausarta Draw.io — carpeta: {PROJECT_ROOT}")
    print(f"Local: http://127.0.0.1:{DEFAULT_PORT}/")
    create_app().run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=local_dev, use_reloader=local_dev)
