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
from generator.download_store import DownloadStore
from generator.glpi_client import GlpiClient, GlpiError, build_customer_catalog
from generator.knowledge_base import learn_from_drawio
from generator.site_directory import SiteDirectory, apply_saved_addresses
from generator.device_catalog import build_device_catalog
from generator.web_adapter import build_drawio_from_data, form_to_data, form_to_structured_data


PROJECT_ROOT = Path(__file__).resolve().parent
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
DEFAULT_HOST = os.environ.get("DRAWIO_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("DRAWIO_PORT", os.environ.get("PORT", "8000")))

# Configure security logging
security_logger = logging.getLogger("security")
security_logger.setLevel(logging.INFO)
if not security_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s [SECURITY] %(message)s"))
    security_logger.addHandler(handler)


def _positive_integer(value: object, field_name: str) -> int:
    text = str(value or "").strip()
    if not text.isdigit() or int(text) <= 0:
        raise ValueError(f"El campo '{field_name}' debe ser un ID entero positivo.")
    return int(text)


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"), static_folder=str(PROJECT_ROOT / "static"))
    app.config["DEFAULT_LIBRARY"] = os.environ.get(
        "DRAWIO_LIBRARY_PATH",
        "libreria_Ausarta_JUN_2026.xml",
    )
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("DRAWIO_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
    
    # Security: Generate strong SECRET_KEY if not provided
    secret_key = os.environ.get("DRAWIO_SECRET_KEY", "").strip()
    if not secret_key:
        security_logger.warning("DRAWIO_SECRET_KEY no esta configurado. Generando clave temporal (las sesiones se perderan al reiniciar).")
        secret_key = secrets.token_hex(32)
    app.config["SECRET_KEY"] = secret_key
    
    app.config["AUTH_REQUIRED"] = os.environ.get("DRAWIO_AUTH_REQUIRED", "0") == "1"
    
    # Security: Session configuration
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("DRAWIO_COOKIE_SECURE", "0") == "1"
    app.config["SESSION_COOKIE_NAME"] = "drawio_session"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=int(os.environ.get("DRAWIO_SESSION_HOURS", "8")))
    
    # Security: CSRF Protection
    app.config["WTF_CSRF_TIME_LIMIT"] = None  # CSRF tokens never expire (tied to session)
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
    
    # Security: HTTP Security Headers (Talisman)
    # Only enforce HTTPS if explicitly enabled
    force_https = os.environ.get("DRAWIO_FORCE_HTTPS", "0") == "1"
    csp = {
        'default-src': "'self'",
        'script-src': ["'self'", "'unsafe-inline'", "embed.diagrams.net"],
        'style-src': ["'self'", "'unsafe-inline'"],
        'img-src': ["'self'", "data:", "embed.diagrams.net"],
        'frame-src': ["'self'", "embed.diagrams.net"],
        'connect-src': ["'self'"],
    }
    Talisman(
        app,
        force_https=force_https,
        strict_transport_security=force_https,
        content_security_policy=csp,
        content_security_policy_nonce_in=['script-src'],
        frame_options='SAMEORIGIN',
        referrer_policy='strict-origin-when-cross-origin',
    )
    
    app.config["PREVIEW_URL"] = os.environ.get("DRAWIO_PREVIEW_URL", "https://embed.diagrams.net/").rstrip("/")

    def current_technician() -> dict:
        return session.get("technician") or {"username": "local", "name": "Tecnico local"}

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
            return [], str(exc)

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
                error = "GLPI no esta configurado."
                security_logger.warning(f"Login attempt failed: GLPI not configured (IP: {client_ip})")
            elif not username or not password:
                error = "Introduce usuario y contraseña de GLPI."
                security_logger.warning(f"Login attempt failed: empty credentials (IP: {client_ip})")
            else:
                try:
                    session.clear()
                    session["technician"] = client.authenticate_user(username, password)
                    session.permanent = True
                    security_logger.info(f"Login successful: user={username}, IP={client_ip}")
                    return redirect(request.args.get("next") or url_for("index"))
                except GlpiError:
                    error = "Usuario o contraseña de GLPI incorrectos."
                    security_logger.warning(f"Login attempt failed: invalid credentials for user={username}, IP={client_ip}")
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout() -> Response:
        username = session.get("technician", {}).get("username", "unknown")
        client_ip = get_remote_address()
        session.clear()
        security_logger.info(f"Logout: user={username}, IP={client_ip}")
        return redirect(url_for("login"))

    def index_context(**extra):
        glpi_customers, glpi_error = load_glpi_catalog()
        context = {
            "device_catalog": build_device_catalog(app.config["DEFAULT_LIBRARY"]),
            "glpi_customers": glpi_customers,
            "glpi_error": glpi_error,
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
                entity_id = _positive_integer(selected_entity, "entity_id")
                client = GlpiClient.from_environment()
                if not client:
                    raise GlpiError("GLPI no esta configurado.")
                for diagram in client.list_network_diagrams(entity_id):
                    diagram_id = diagram.get("id")
                    if not str(diagram_id or "").isdigit():
                        continue
                    diagram_rows.append(
                        {
                            "id": int(diagram_id),
                            "name": diagram.get("name") or f"Diagrama #{diagram_id}",
                            "description": diagram.get("shortdescription", ""),
                            "state": diagram.get("plugin_archimap_graphstates_id", ""),
                            "url": client.diagram_url(int(diagram_id)),
                        }
                    )
            except (ValueError, GlpiError) as exc:
                glpi_error = str(exc)
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
            item["created_label"] = datetime.fromtimestamp(item["created_at"]).strftime("%d/%m/%Y %H:%M")
            item["url"] = client.diagram_url(item["diagram_id"]) if client else ""
            rows.append(item)
        return render_template(
            "my_diagrams.html",
            diagrams=rows,
            technician=technician,
        )

    @app.route("/upload-draw", methods=["GET", "POST"])
    @login_required
    @limiter.limit("20 per hour")
    def upload_draw() -> str:
        glpi_customers, glpi_error = load_glpi_catalog()
        upload_error = ""
        upload_result = None
        if request.method == "POST":
            entity_id = request.form.get("glpi_entity_id", "").strip()
            client_name = request.form.get("glpi_cliente", "").strip()
            site_name = request.form.get("glpi_sede", "").strip()
            uploaded_file = request.files.get("drawio_file")
            client_ip = get_remote_address()
            technician_name = current_technician().get("name", "unknown")
            
            if not entity_id:
                upload_error = "Selecciona una sede de GLPI."
            elif not uploaded_file or not uploaded_file.filename:
                upload_error = "Selecciona un archivo .drawio."
            elif not uploaded_file.filename.lower().endswith((".drawio", ".xml")):
                upload_error = "El archivo debe tener extension .drawio o .xml."
                security_logger.warning(f"Upload attempt with invalid file type: {uploaded_file.filename}, user={technician_name}, IP={client_ip}")
            else:
                raw = uploaded_file.read()
                try:
                    validated_entity_id = _positive_integer(entity_id, "glpi_entity_id")
                    xml = raw.decode("utf-8-sig")
                    root = DefusedET.fromstring(xml)
                    if root.tag != "mxfile":
                        raise ValueError("El documento no contiene un mxfile de Draw.io.")
                    client = GlpiClient.from_environment()
                    if not client:
                        raise GlpiError("GLPI no esta configurado.")
                    existing_diagrams = client.list_network_diagrams(validated_entity_id)
                    if existing_diagrams and request.form.get("allow_duplicate") != "1":
                        existing_ids = ", ".join(
                            f"#{item['id']}" for item in existing_diagrams if str(item.get("id", "")).isdigit()
                        )
                        raise ValueError(
                            f"Esta sede ya tiene diagramas ({existing_ids or 'existentes'}). "
                            "Revísalos o marca la confirmación para subir otro."
                        )
                    diagram_id = client.create_network_diagram(
                        entity_id=validated_entity_id,
                        name=Path(uploaded_file.filename).stem,
                        description=(
                            f"Diagrama historico de {client_name} - {site_name}. "
                            f"Subido por {current_technician()['name']}"
                        ),
                        graph_xml=xml,
                    )
                    ACTIVITY.add(
                        diagram_id=diagram_id,
                        entity_id=validated_entity_id,
                        diagram_name=Path(uploaded_file.filename).stem,
                        client_name=client_name,
                        site_name=site_name,
                        technician=current_technician(),
                        source="Archivo antiguo",
                    )
                    learned_models = learn_from_drawio(xml, uploaded_file.filename)
                    upload_result = {
                        "id": diagram_id,
                        "url": client.diagram_url(diagram_id),
                        "filename": uploaded_file.filename,
                        "cliente": client_name,
                        "sede": site_name,
                        "learned_models": learned_models,
                    }
                    security_logger.info(f"File uploaded successfully: diagram_id={diagram_id}, file={uploaded_file.filename}, user={technician_name}, IP={client_ip}")
                except (UnicodeDecodeError, DefusedET.ParseError, DefusedXmlException, ValueError, GlpiError) as exc:
                    upload_error = f"No se ha podido subir el diagrama: {exc}"
                    security_logger.warning(f"Upload failed: {exc}, user={technician_name}, IP={client_ip}")
        return render_template(
            "upload_draw.html",
            glpi_customers=glpi_customers,
            glpi_error=glpi_error,
            upload_error=upload_error,
            upload_result=upload_result,
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
                glpi_entity_id = _positive_integer(glpi_entity_id, "glpi_entity_id")
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
        if glpi_entity_id:
            client = GlpiClient.from_environment()
            if client:
                try:
                    existing_diagrams = client.list_network_diagrams(glpi_entity_id)
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
            "existing_diagrams": [
                {
                    "id": int(item["id"]),
                    "name": item.get("name") or f"Diagrama #{item['id']}",
                    "url": client.diagram_url(int(item["id"])) if client else "",
                }
                for item in existing_diagrams
                if str(item.get("id", "")).isdigit()
            ],
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
            entity_id = _positive_integer(payload.get("entity_id"), "entity_id")
            existing = client.list_network_diagrams(entity_id)
            allow_duplicate = request.form.get("allow_duplicate") == "1"
            if existing and not allow_duplicate:
                return Response(
                    "Esta sede ya tiene un diagrama. Revisa el existente antes de publicar otro.",
                    status=409,
                    mimetype="text/plain; charset=utf-8",
                )
            technician = payload.get("technician") or current_technician()
            diagram_id = client.create_network_diagram(
                entity_id=entity_id,
                name=f"{payload['cliente']} - {payload['sede']}",
                description=(
                    f"Diagrama de red generado para {payload['cliente']}. "
                    f"Subido por {technician.get('name') or technician.get('username')}"
                ),
                graph_xml=payload["xml"],
            )
            ACTIVITY.add(
                diagram_id=diagram_id,
                entity_id=entity_id,
                diagram_name=f"{payload['cliente']} - {payload['sede']}",
                client_name=payload["cliente"],
                site_name=payload["sede"],
                technician=technician,
                source="Generado",
            )
        except ValueError as exc:
            return Response(str(exc), status=400, mimetype="text/plain; charset=utf-8")
        except GlpiError as exc:
            return Response(str(exc), status=502, mimetype="text/plain; charset=utf-8")
        DOWNLOADS.update_payload(token, uploaded=True)
        return Response(
            json.dumps({"id": diagram_id, "url": client.diagram_url(diagram_id)}),
            mimetype="application/json",
        )

    return app


if __name__ == "__main__":
    create_app().run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=False)
