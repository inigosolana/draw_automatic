from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, send_file, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

from app_context import (
    ADMIN_USERS,
    can_access_pending,
    current_technician,
    get_drawio_stores,
    login_required,
    security_logger,
)
from web.services.glpi_catalog import glpi_diagram_rows, load_glpi_catalog, relevant_entity_ids
from generator.diagram_metadata import enrich_activity_rows
from generator.drawio_reverse import parse_drawio_to_form
from generator.glpi_client import GlpiClient, GlpiError
from generator.pdf_drawio import PdfDrawioError, extract_drawio_from_pdf
from generator.safe_errors import public_error_message
from generator.utils import is_safe_redirect, positive_integer, technician_is_admin

_DRAWIO_CORS_ORIGINS = frozenset(
    {
        "https://embed.diagrams.net",
        "https://app.diagrams.net",
    }
)


def _content_disposition(filename: str) -> str:
    """Construye una cabecera Content-Disposition segura para descargas.

    Evita la inyeccion de cabeceras HTTP: elimina CR/LF y caracteres de
    control, y escapa/quita comillas del nombre ASCII. Añade filename*
    (RFC 5987) con el nombre original codificado para preservar Unicode.
    """
    raw = (filename or "").strip() or "diagram.drawio"
    # Elimina saltos de linea y caracteres de control que romperian la cabecera.
    raw = re.sub(r"[\r\n]", "", raw)
    ascii_name = "".join(ch for ch in raw if 32 <= ord(ch) < 127 and ch != '"') or "diagram.drawio"
    encoded = quote(raw, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def _validate_drawio_xml(xml: str) -> str:
    cleaned = (xml or "").strip()
    if not cleaned.startswith("<") or ("<mxfile" not in cleaned and "<mxGraphModel" not in cleaned):
        raise ValueError("El XML no parece un diagrama draw.io valido.")
    return cleaned


def _preview_close_url() -> str:
    next_url = request.args.get("next", "").strip()
    if is_safe_redirect(next_url):
        return next_url
    return url_for("home.index")


def _library_cors_response(response: Response) -> Response:
    origin = request.headers.get("Origin", "").strip()
    if origin in _DRAWIO_CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        response.headers["Access-Control-Allow-Origin"] = "https://embed.diagrams.net"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "86400"
    response.headers["Vary"] = "Origin"
    return response


def _external_base_url() -> str:
    explicit = os.environ.get("DRAWIO_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    if request.is_secure or os.environ.get("DRAWIO_COOKIE_SECURE", "0") == "1":
        host = (request.host or "").split(":")[0]
        return f"https://{host}"
    return request.host_url.rstrip("/")


def _preview_library_url() -> str:
    library_path = Path(current_app.config["DEFAULT_LIBRARY"])
    library_version = int(library_path.stat().st_mtime) if library_path.is_file() else 0
    library_path_url = url_for("diagrams.drawio_library", v=library_version)
    return f"{_external_base_url()}{library_path_url}"


def _normalize_preview_xml(xml: str) -> str:
    """Adapt tall diagrams for preview: fit page size to content and reset scroll offset."""
    cleaned = (xml or "").strip()
    if not cleaned:
        return cleaned

    max_right = 0
    max_bottom = 0
    # Casa la etiqueta de apertura tanto autocerrada (<mxGeometry .../>) como con
    # hijos (<mxGeometry ...> ... </mxGeometry>, que draw.io emite con waypoints).
    for fragment in re.finditer(r"<mxGeometry\b[^>]*>", cleaned):
        block = fragment.group(0)
        x_match = re.search(r'\bx="(\d+)"', block)
        y_match = re.search(r'\by="(\d+)"', block)
        width_match = re.search(r'\bwidth="(\d+)"', block)
        height_match = re.search(r'\bheight="(\d+)"', block)
        if x_match and y_match and width_match and height_match:
            x = int(x_match.group(1))
            y = int(y_match.group(1))
            width = int(width_match.group(1))
            height = int(height_match.group(1))
            max_right = max(max_right, x + width)
            max_bottom = max(max_bottom, y + height)

    if max_bottom > 0:
        padding = 24
        target_width = max(max_right + padding, 400)
        target_height = max_bottom + padding
        if re.search(r'pageWidth="\d+"', cleaned):
            cleaned = re.sub(
                r'pageWidth="\d+"',
                f'pageWidth="{target_width}"',
                cleaned,
                count=1,
            )
        if re.search(r'pageHeight="\d+"', cleaned):
            cleaned = re.sub(
                r'pageHeight="\d+"',
                f'pageHeight="{target_height}"',
                cleaned,
                count=1,
            )

    cleaned = re.sub(r'(<mxGraphModel\b[^>]*\b)dx="\d+"', r'\1dx="0"', cleaned, count=1)
    cleaned = re.sub(r'(<mxGraphModel\b[^>]*\b)dy="\d+"', r'\1dy="0"', cleaned, count=1)
    cleaned = re.sub(r'(<mxGraphModel\b[^>]*\b)grid="1"', r'\1grid="0"', cleaned, count=1)
    return cleaned


def _preview_embed_url(library_clibs: str) -> str:
    base = current_app.config["PREVIEW_URL"]
    return (
        f"{base}/?embed=1&ui=min&spin=1&proto=json&libraries=1&configure=1"
        f"&grid=0&clibs={library_clibs}"
    )


def _preview_template_context(**extra) -> dict:
    library_url = _preview_library_url()
    library_clibs = "U" + quote(library_url, safe="")
    return {
        "preview_base_url": current_app.config["PREVIEW_URL"],
        "preview_embed_url": _preview_embed_url(library_clibs),
        "library_url": library_url,
        "library_clibs": library_clibs,
        **extra,
    }


def create_diagrams_blueprint(limiter: Limiter, csrf: CSRFProtect) -> Blueprint:
    bp = Blueprint("diagrams", __name__)

    @bp.get("/health")
    @csrf.exempt
    @limiter.limit("30 per minute")
    def health() -> Response:
        return jsonify({"status": "ok"})

    @bp.route("/drawio-library.xml", methods=["GET", "OPTIONS"])
    @csrf.exempt
    @limiter.limit("60 per minute")
    def drawio_library() -> Response:
        if request.method == "OPTIONS":
            return _library_cors_response(Response(status=204))

        library_path = Path(current_app.config["DEFAULT_LIBRARY"])
        if not library_path.is_file():
            return Response("Biblioteca no encontrada.", status=404, mimetype="text/plain; charset=utf-8")

        raw_bytes = library_path.read_bytes()
        accept_encoding = request.headers.get("Accept-Encoding", "")
        if "gzip" in accept_encoding.lower() and len(raw_bytes) > 512_000:
            import gzip

            payload = gzip.compress(raw_bytes, compresslevel=6)
            response = Response(payload, mimetype="application/xml")
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Content-Length"] = str(len(payload))
            response.headers["Vary"] = "Accept-Encoding"
        else:
            response = send_file(
                library_path,
                mimetype="application/xml",
                download_name=library_path.name,
                conditional=True,
                max_age=3600,
            )
        return _library_cors_response(response)

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
                client = GlpiClient.from_environment()
                if not client:
                    raise GlpiError("GLPI no esta configurado.")
                # Incluir también la entidad cliente (padre): en GLPI hay
                # diagramas asociados al cliente y no a la sede concreta.
                relevant_ids = relevant_entity_ids(entity_id, glpi_customers)
                diagram_rows = glpi_diagram_rows(client, relevant_ids, drawio_stores.activity)
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

    @bp.get("/my-diagrams")
    @login_required
    def my_diagrams() -> str:
        drawio_stores = get_drawio_stores()
        technician = current_technician()
        username = technician.get("username") or technician.get("name") or "local"
        client = GlpiClient.from_environment()
        rows = enrich_activity_rows(
            drawio_stores.activity.list_for_technician(username),
            client,
        )
        deleted_id = request.args.get("deleted", "").strip()
        replaced_id = request.args.get("replaced", "").strip()
        delete_error = request.args.get("error", "").strip()
        return render_template(
            "my_diagrams.html",
            diagrams=rows,
            technician=technician,
            deleted_id=deleted_id if deleted_id.isdigit() else "",
            replaced_id=replaced_id if replaced_id.isdigit() else "",
            delete_error=delete_error,
        )

    @bp.post("/my-diagrams/delete")
    @login_required
    @limiter.limit("30 per hour")
    def delete_my_diagram() -> Response:
        drawio_stores = get_drawio_stores()
        technician = current_technician()
        username = (technician.get("username") or technician.get("name") or "local").strip()
        back = url_for("diagrams.my_diagrams")

        diagram_id_raw = request.form.get("diagram_id", "").strip()
        if not diagram_id_raw.isdigit():
            return redirect(f"{back}?error=ID+de+diagrama+no+valido.")
        diagram_id = int(diagram_id_raw)

        # Autorización: admin puede borrar cualquiera; un técnico solo los suyos.
        is_admin = technician_is_admin(technician, ADMIN_USERS)
        owners = drawio_stores.activity.diagram_owners(diagram_id)
        if not is_admin and username not in owners:
            security_logger.warning(
                "Intento de borrado no autorizado: diagram_id=%s user=%s IP=%s",
                diagram_id,
                username,
                get_remote_address(),
            )
            return redirect(f"{back}?error=Solo+puedes+borrar+tus+propios+diagramas.")

        client = GlpiClient.from_environment()
        if not client:
            return redirect(f"{back}?error=GLPI+no+esta+configurado.")
        try:
            client.delete_network_diagram(diagram_id)
            removed_rows = drawio_stores.activity.delete_by_diagram_id(diagram_id)
            drawio_stores.catalog.clear("admin_coverage")
            security_logger.info(
                "Diagrama borrado: diagram_id=%s user=%s admin=%s activity_rows=%s IP=%s",
                diagram_id,
                username,
                is_admin,
                removed_rows,
                get_remote_address(),
            )
        except GlpiError as exc:
            security_logger.warning(
                "Borrado de diagrama fallido: diagram_id=%s user=%s error=%s IP=%s",
                diagram_id,
                username,
                exc,
                get_remote_address(),
            )
            return redirect(
                f"{back}?error=" + quote(public_error_message(str(exc), context="borrado del diagrama"))
            )
        return redirect(f"{back}?deleted={diagram_id}")

    @bp.post("/my-diagrams/replace")
    @login_required
    @limiter.limit("30 per hour")
    def replace_my_diagram() -> Response:
        """Sustituye el diagrama por otro archivo (.drawio/.xml/.pdf) subido,
        guardándolo como nueva versión en GLPI. Misma autorización que borrar:
        admin cualquiera; un técnico solo los suyos."""
        drawio_stores = get_drawio_stores()
        technician = current_technician()
        username = (technician.get("username") or technician.get("name") or "local").strip()
        back = url_for("diagrams.my_diagrams")

        diagram_id_raw = request.form.get("diagram_id", "").strip()
        if not diagram_id_raw.isdigit():
            return redirect(f"{back}?error=ID+de+diagrama+no+valido.")
        diagram_id = int(diagram_id_raw)

        is_admin = technician_is_admin(technician, ADMIN_USERS)
        owners = drawio_stores.activity.diagram_owners(diagram_id)
        if not is_admin and username not in owners:
            security_logger.warning(
                "Intento de cambio no autorizado: diagram_id=%s user=%s IP=%s",
                diagram_id,
                username,
                get_remote_address(),
            )
            return redirect(f"{back}?error=" + quote("Solo puedes cambiar tus propios diagramas."))

        uploaded = request.files.get("drawio_file")
        if not uploaded or not uploaded.filename:
            return redirect(f"{back}?error=" + quote("Elige un archivo .drawio, .xml o .pdf."))
        if not uploaded.filename.lower().endswith((".drawio", ".xml", ".pdf")):
            return redirect(f"{back}?error=" + quote("Formato no valido: usa .drawio, .xml o .pdf."))

        client = GlpiClient.from_environment()
        if not client:
            return redirect(f"{back}?error=GLPI+no+esta+configurado.")
        try:
            raw = uploaded.read()
            if uploaded.filename.lower().endswith(".pdf"):
                xml = extract_drawio_from_pdf(raw)
            else:
                xml = raw.decode("utf-8-sig")
            xml = _validate_drawio_xml(xml)
            # Una sola sesion GLPI para guardar la nueva version.
            with client.batch_session():
                client.save_network_diagram_version(diagram_id, xml, technician=technician)
            drawio_stores.catalog.clear("admin_coverage")
            security_logger.info(
                "Diagrama cambiado por otro: diagram_id=%s user=%s file=%s IP=%s",
                diagram_id,
                username,
                uploaded.filename,
                get_remote_address(),
            )
        except (UnicodeDecodeError, PdfDrawioError, ValueError, GlpiError) as exc:
            return redirect(
                f"{back}?error=" + quote(public_error_message(str(exc), context="cambio del diagrama"))
            )
        return redirect(f"{back}?replaced={diagram_id}")

    @bp.get("/download/<token>")
    @login_required
    def download(token: str) -> Response:
        payload = get_drawio_stores().downloads.get(token)
        if not payload:
            return Response("Archivo no encontrado.", status=404, mimetype="text/plain; charset=utf-8")
        if not can_access_pending(payload):
            return Response("No autorizado.", status=403, mimetype="text/plain; charset=utf-8")
        if payload.get("uploaded"):
            return Response(
                "El diagrama ya fue publicado en GLPI y no puede descargarse de nuevo.",
                status=410,
                mimetype="text/plain; charset=utf-8",
            )
        return Response(
            payload["xml"],
            mimetype="application/xml; charset=utf-8",
            headers={"Content-Disposition": _content_disposition(payload["filename"])},
        )

    @bp.get("/preview/<token>")
    @login_required
    def preview_drawio(token: str) -> str:
        payload = get_drawio_stores().downloads.get(token)
        if not payload:
            return Response("Diagrama pendiente no encontrado.", status=404)
        if not can_access_pending(payload):
            return Response("No autorizado.", status=403)
        return render_template(
            "preview.html",
            **_preview_template_context(
                token=token,
                filename=payload["filename"],
                # Normalizado igual que la ruta /xml (ajusta tamaño de página y
                # resetea scroll) para que el pendiente abra encuadrado como el de GLPI.
                xml=_normalize_preview_xml(payload["xml"]),
                xml_url=url_for("diagrams.preview_drawio_xml", token=token),
                save_url=url_for("diagrams.preview_save", token=token),
                close_url=_preview_close_url(),
                preview_label="Previsualización editable",
                # Diagrama recién generado (aún no en GLPI): autoguardar en
                # servidor es seguro (actualiza el pendiente, sin crear versiones).
                autosave_server=True,
            ),
        )

    @bp.get("/preview/<token>/xml")
    @login_required
    def preview_drawio_xml(token: str) -> Response:
        payload = get_drawio_stores().downloads.get(token)
        if not payload:
            return Response("Diagrama pendiente no encontrado.", status=404)
        if not can_access_pending(payload):
            return Response("No autorizado.", status=403)
        return Response(
            _normalize_preview_xml(payload["xml"]),
            mimetype="application/xml; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @bp.post("/preview/<token>/save")
    @login_required
    @limiter.limit("60 per hour")
    def preview_save(token: str) -> Response:
        payload = get_drawio_stores().downloads.get(token)
        if not payload:
            return jsonify({"error": "Diagrama pendiente no encontrado."}), 404
        if not can_access_pending(payload):
            return jsonify({"error": "No autorizado."}), 403
        if payload.get("uploaded"):
            return jsonify({"error": "El diagrama ya fue publicado en GLPI."}), 409
        body = request.get_json(silent=True) or {}
        try:
            xml = _validate_drawio_xml(str(body.get("xml", "")))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        get_drawio_stores().downloads.update_payload(token, xml=xml)
        technician = current_technician()
        tech_name = (technician.get("name") or technician.get("username") or "").strip()
        security_logger.info(
            "Preview diagram saved: token=%s user=%s",
            token,
            tech_name,
        )
        return jsonify({"ok": True, "message": "Cambios guardados en el diagrama pendiente."})

    @bp.get("/preview/glpi/<int:diagram_id>")
    @login_required
    def preview_glpi_diagram(diagram_id: int) -> str | Response:
        client = GlpiClient.from_environment()
        if not client:
            return Response(
                "GLPI no esta configurado.",
                status=503,
                mimetype="text/plain; charset=utf-8",
            )
        try:
            xml, name = client.get_network_diagram_xml(diagram_id)
        except GlpiError as exc:
            return Response(
                public_error_message(str(exc), context="carga del diagrama"),
                status=404,
                mimetype="text/plain; charset=utf-8",
            )
        name = (name or "diagrama") if isinstance(name, str) else "diagrama"
        filename = name if name.lower().endswith(".drawio") else f"{name}.drawio"
        return render_template(
            "preview.html",
            **_preview_template_context(
                token=str(diagram_id),
                filename=filename,
                xml="",
                xml_url=url_for("diagrams.preview_glpi_xml", diagram_id=diagram_id),
                save_url=url_for("diagrams.preview_glpi_save", diagram_id=diagram_id),
                close_url=_preview_close_url(),
                preview_label="Previsualización editable del diagrama",
            ),
        )

    @bp.get("/preview/glpi/<int:diagram_id>/xml")
    @login_required
    def preview_glpi_xml(diagram_id: int) -> Response:
        client = GlpiClient.from_environment()
        if not client:
            return Response("GLPI no esta configurado.", status=503)
        try:
            xml, _name = client.get_network_diagram_xml(diagram_id)
        except GlpiError as exc:
            return Response(
                public_error_message(str(exc), context="carga del diagrama"),
                status=404,
            )
        return Response(
            _normalize_preview_xml(xml),
            mimetype="application/xml; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @bp.get("/api/diagram/<int:diagram_id>/as-form")
    @login_required
    @limiter.limit("60 per hour")
    def diagram_as_form(diagram_id: int) -> Response:
        """Devuelve un diagrama existente de GLPI como datos de formulario
        (terminales + conectividad), para fusionarlo con lo nuevo de una OT."""
        client = GlpiClient.from_environment()
        if not client:
            return jsonify({"error": "GLPI no esta configurado."}), 503
        try:
            xml, _name = client.get_network_diagram_xml(diagram_id)
        except GlpiError as exc:
            return jsonify({"error": public_error_message(str(exc), context="carga del diagrama")}), 404
        return jsonify(parse_drawio_to_form(xml))

    @bp.post("/preview/glpi/<int:diagram_id>/save")
    @login_required
    @limiter.limit("60 per hour")
    def preview_glpi_save(diagram_id: int) -> Response:
        client = GlpiClient.from_environment()
        if not client:
            return jsonify({"error": "GLPI no esta configurado."}), 503
        body = request.get_json(silent=True) or {}
        try:
            xml = _validate_drawio_xml(str(body.get("xml", "")))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        technician = current_technician()
        try:
            # Una sola sesion GLPI para guardar la version y releer el diagrama.
            with client.batch_session():
                version_id, version_name = client.save_network_diagram_version(
                    diagram_id,
                    xml,
                    technician=technician,
                )
                diagram = client.get_network_diagram(diagram_id)
        except GlpiError as exc:
            return jsonify(
                {"error": public_error_message(str(exc), context="guardado del diagrama en GLPI")}
            ), 502
        drawio_stores = get_drawio_stores()
        entity_id = int(diagram.get("entities_id") or 0)
        activity_rows = drawio_stores.activity.map_for_entity(entity_id) if entity_id else {}
        source_activity = activity_rows.get(diagram_id) or activity_rows.get(int(diagram_id))
        if source_activity:
            drawio_stores.activity.add(
                diagram_id=version_id,
                entity_id=entity_id,
                diagram_name=version_name,
                client_name=source_activity.get("client_name", ""),
                site_name=source_activity.get("site_name", ""),
                technician=technician,
                source="Version",
            )
        tech_name = (technician.get("name") or technician.get("username") or "").strip()
        security_logger.info(
            "GLPI diagram saved from preview: diagram_id=%s version_id=%s version_name=%s user=%s",
            diagram_id,
            version_id,
            version_name,
            tech_name,
        )
        return jsonify(
            {
                "ok": True,
                "message": f"Diagrama guardado. Copia de version: {version_name}.",
                "version_id": version_id,
                "version_name": version_name,
                "version_url": client.diagram_url(version_id),
            }
        )

    return bp
