from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException
from flask import Blueprint, Response, current_app, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import web_app
from generator.comms_client import CommsClient, CommsError, import_products_text
from generator.diagram_metadata import (
    build_diagram_description,
    format_activity_timestamp,
    unique_diagram_name,
)
from generator.glpi_merge import merge_import_with_glpi
from generator.knowledge_base import learn_from_drawio
from generator.safe_errors import public_error_message
from generator.utils import positive_integer
from generator.web_adapter import build_drawio_from_data, form_to_data, form_to_structured_data
from generator.work_order_text_parser import parse_work_order_paste
from web_app import (
    _glpi_diagram_rows,
    current_technician,
    get_drawio_stores,
    index_context,
    load_glpi_catalog,
    login_required,
    security_logger,
)


def create_glpi_import_blueprint(limiter: Limiter) -> Blueprint:
    bp = Blueprint("glpi_import", __name__)

    @bp.get("/")
    @login_required
    def index() -> str:
        return render_template(
            "index.html",
            **index_context(form_data={"library_path": current_app.config["DEFAULT_LIBRARY"]}),
        )

    @bp.post("/generate")
    @login_required
    @limiter.limit("30 per hour")
    def generate() -> str:
        drawio_stores = get_drawio_stores()
        form_data = request.form.to_dict()
        form_data.setdefault("library_path", current_app.config["DEFAULT_LIBRARY"])
        try:
            data = form_to_data(form_data)
            structured_data = form_to_structured_data(form_data)
            generated = build_drawio_from_data(
                data, form_data.get("library_path", current_app.config["DEFAULT_LIBRARY"])
            )
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
            drawio_stores.sites.set(
                glpi_entity_id,
                generated.data.get("direccion", ""),
                technician.get("name") or technician.get("username") or "desconocido",
            )
        token = uuid.uuid4().hex
        existing_diagrams: list[dict] = []
        glpi_client = web_app.GlpiClient.from_environment()
        if glpi_entity_id and glpi_client:
            try:
                existing_diagrams = _glpi_diagram_rows(glpi_client, glpi_entity_id, drawio_stores.activity)
            except web_app.GlpiError:
                existing_diagrams = []
        technician = current_technician()
        drawio_stores.downloads[token] = {
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
            "download_url": url_for("diagrams.download", token=token),
            "filename": generated.filename,
            "structured_json": json.dumps(structured_data, ensure_ascii=False, indent=2),
            "glpi_diagram_id": None,
            "glpi_diagram_url": "",
            "glpi_upload_error": "",
            "confirm_url": url_for("glpi_import.confirm_glpi", token=token) if glpi_entity_id else "",
            "preview_url": url_for("diagrams.preview_drawio", token=token),
            "technician": technician,
            "existing_diagrams": existing_diagrams,
        }
        return render_template(
            "index.html",
            **index_context(form_data=form_data, preview=preview, errors=[]),
        )

    @bp.post("/confirm-glpi/<token>")
    @login_required
    def confirm_glpi(token: str) -> str:
        drawio_stores = get_drawio_stores()
        payload = drawio_stores.downloads.get(token)
        if not payload:
            return Response("Diagrama pendiente no encontrado.", status=404, mimetype="text/plain; charset=utf-8")
        if payload["uploaded"]:
            return Response("El diagrama ya fue subido a GLPI.", status=409, mimetype="text/plain; charset=utf-8")
        client = web_app.GlpiClient.from_environment()
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
            drawio_stores.activity.add(
                diagram_id=diagram_id,
                entity_id=entity_id,
                diagram_name=diagram_name,
                client_name=payload["cliente"],
                site_name=payload["sede"],
                technician=technician,
                source="Generado",
            )
        except ValueError as exc:
            return Response(
                public_error_message(str(exc), context="publicacion en GLPI"),
                status=400,
                mimetype="text/plain; charset=utf-8",
            )
        except web_app.GlpiError as exc:
            security_logger.warning(f"GLPI confirm failed: {exc} (IP: {get_remote_address()})")
            return Response(
                public_error_message(str(exc), context="publicacion en GLPI"),
                status=502,
                mimetype="text/plain; charset=utf-8",
            )
        drawio_stores.downloads.update_payload(token, uploaded=True)
        return Response(
            json.dumps({"id": diagram_id, "url": client.diagram_url(diagram_id)}),
            mimetype="application/json",
        )

    @bp.post("/api/import-work-order")
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
                    "glpi_message": glpi_merge.get("message") or public_error_message(
                        glpi_error, context="sincronizacion GLPI"
                    ),
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

    @bp.route("/upload-draw", methods=["GET", "POST"])
    @login_required
    @limiter.limit("20 per hour")
    def upload_draw() -> str:
        drawio_stores = get_drawio_stores()
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
                    client = web_app.GlpiClient.from_environment()
                    if not client:
                        raise web_app.GlpiError("GLPI no esta configurado.")
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
                            drawio_stores.activity.add(
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
                        except (
                            UnicodeDecodeError,
                            DefusedET.ParseError,
                            DefusedXmlException,
                            ValueError,
                            web_app.GlpiError,
                        ) as exc:
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
                except (ValueError, web_app.GlpiError) as exc:
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

    return bp
