from __future__ import annotations

import json

from flask import Blueprint, Response, current_app, render_template, request
from flask_limiter import Limiter
from flask_wtf.csrf import CSRFProtect

import web_app
from generator.diagram_metadata import format_activity_timestamp
from generator.safe_errors import public_error_message
from generator.utils import positive_integer
from web_app import (
    _glpi_diagram_rows,
    current_technician,
    get_drawio_stores,
    load_glpi_catalog,
    login_required,
)


def create_diagrams_blueprint(limiter: Limiter, csrf: CSRFProtect) -> Blueprint:
    bp = Blueprint("diagrams", __name__)

    @bp.get("/health")
    @csrf.exempt
    @limiter.limit("30 per minute")
    def health() -> Response:
        return Response(
            json.dumps({"status": "ok"}),
            mimetype="application/json",
        )

    @bp.get("/diagrams")
    @login_required
    def diagrams() -> str:
        drawio_stores = get_drawio_stores()
        glpi_customers, glpi_error = load_glpi_catalog()
        selected_entity = request.args.get("entity_id", "").strip()
        diagram_rows: list[dict] = []
        if selected_entity:
            try:
                entity_id = positive_integer(selected_entity, "entity_id")
                client = web_app.GlpiClient.from_environment()
                if not client:
                    raise web_app.GlpiError("GLPI no esta configurado.")
                diagram_rows = _glpi_diagram_rows(client, entity_id, drawio_stores.activity)
            except (ValueError, web_app.GlpiError) as exc:
                glpi_error = public_error_message(str(exc), context="consulta de diagramas GLPI")
        return render_template(
            "diagrams.html",
            glpi_customers=glpi_customers,
            glpi_error=glpi_error,
            diagrams=diagram_rows,
            selected_entity=selected_entity,
            technician=current_technician(),
        )

    @bp.get("/my-diagrams")
    @login_required
    def my_diagrams() -> str:
        drawio_stores = get_drawio_stores()
        technician = current_technician()
        username = technician.get("username") or technician.get("name") or "local"
        client = web_app.GlpiClient.from_environment()
        rows = []
        for item in drawio_stores.activity.list_for_technician(username):
            item["created_label"] = format_activity_timestamp(item["created_at"])
            item["technician"] = item.get("technician_name") or username
            item["url"] = client.diagram_url(item["diagram_id"]) if client else ""
            rows.append(item)
        return render_template(
            "my_diagrams.html",
            diagrams=rows,
            technician=technician,
        )

    @bp.get("/download/<token>")
    @login_required
    def download(token: str) -> Response:
        payload = get_drawio_stores().downloads.get(token)
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

    @bp.get("/preview/<token>")
    @login_required
    def preview_drawio(token: str) -> str:
        payload = get_drawio_stores().downloads.get(token)
        if not payload:
            return Response("Diagrama pendiente no encontrado.", status=404)
        return render_template(
            "preview.html",
            token=token,
            filename=payload["filename"],
            xml_json=json.dumps(payload["xml"]),
            preview_base_url=current_app.config["PREVIEW_URL"],
        )

    return bp
