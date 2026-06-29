from __future__ import annotations

import json
import uuid

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app_context import (
    current_technician,
    get_drawio_stores,
    login_required,
    security_logger,
)
from web.services.glpi_catalog import glpi_diagram_rows, index_context, load_glpi_catalog
from generator.comms_client import CommsError, import_products_text
from generator.glpi_client import GlpiClient, GlpiError
from generator.work_order_import import import_work_order_by_id
from generator.diagram_metadata import unique_diagram_name
from generator.glpi_merge import merge_import_with_glpi
from generator.safe_errors import public_error_message
from generator.utils import positive_integer
from generator.web_adapter import build_drawio_from_data, form_to_data, form_to_structured_data
from generator.work_order_text_parser import parse_work_order_paste
from web.services.diagram_publish import publish_diagram
from web.services.export import MISSING_SITES_EXPORT_FILENAME, missing_sites_to_xlsx
from web.services.stats import build_missing_sites_rows
from web.services.upload_service import publish_uploaded_files, sync_entity_address


def _pending_generation_url(token: str) -> str:
    return url_for("glpi_import.index", pending=token)


def _preview_drawio_url(token: str) -> str:
    return url_for(
        "diagrams.preview_drawio",
        token=token,
        next=_pending_generation_url(token),
    )


def _preview_from_download(token: str, payload: dict) -> dict:
    drawio_stores = get_drawio_stores()
    entity_id = payload.get("entity_id", "")
    existing_diagrams: list[dict] = []
    glpi_client = GlpiClient.from_environment()
    if entity_id and glpi_client:
        try:
            existing_diagrams = glpi_diagram_rows(glpi_client, entity_id, drawio_stores.activity)
        except GlpiError:
            existing_diagrams = []
    technician = payload.get("technician") or current_technician()
    uploaded = bool(payload.get("uploaded"))
    return {
        "token": token,
        "cliente": payload.get("cliente", ""),
        "sede": payload.get("sede", ""),
        "direccion": payload.get("direccion", ""),
        "template": payload.get("template", ""),
        "total_equipment": payload.get("total_equipment", 0),
        "warnings": payload.get("warnings") or [],
        "download_url": url_for("diagrams.download", token=token),
        "filename": payload.get("filename", ""),
        "structured_json": payload.get("structured_json", "{}"),
        "glpi_diagram_id": payload.get("glpi_diagram_id"),
        "glpi_diagram_url": payload.get("glpi_diagram_url", ""),
        "glpi_upload_error": payload.get("glpi_upload_error", ""),
        "confirm_url": url_for("glpi_import.confirm_glpi", token=token)
        if entity_id and not uploaded
        else "",
        "preview_url": _preview_drawio_url(token),
        "technician": technician,
        "existing_diagrams": existing_diagrams,
        "zabbix_url": payload.get("zabbix_url", ""),
    }


def create_glpi_import_blueprint(limiter: Limiter) -> Blueprint:
    bp = Blueprint("glpi_import", __name__)

    @bp.get("/draw")
    @login_required
    def index() -> str:
        drawio_stores = get_drawio_stores()
        form_data = {"library_path": current_app.config["DEFAULT_LIBRARY"]}
        preview = None
        errors: list[str] = []
        pending = request.args.get("pending", "").strip()
        if pending:
            try:
                payload = drawio_stores.downloads[pending]
            except KeyError:
                errors = ["El diagrama pendiente ya no esta disponible. Genera uno nuevo."]
            else:
                preview = _preview_from_download(pending, payload)
        return render_template(
            "index.html",
            **index_context(form_data=form_data, preview=preview, errors=errors),
        )

    @bp.post("/generate")
    @login_required
    @limiter.limit("50 per hour")
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
        glpi_client = GlpiClient.from_environment()
        if glpi_entity_id and glpi_client:
            try:
                existing_diagrams = glpi_diagram_rows(glpi_client, glpi_entity_id, drawio_stores.activity)
            except GlpiError:
                existing_diagrams = []
        technician = current_technician()
        drawio_stores.downloads[token] = {
            "filename": generated.filename,
            "xml": generated.result.xml,
            "entity_id": glpi_entity_id,
            "cliente": generated.data.get("cliente", ""),
            "sede": generated.data.get("sede", ""),
            "direccion": generated.data.get("direccion", ""),
            "template": generated.data.get("template", ""),
            "total_equipment": generated.total_equipment,
            "warnings": generated.result.warnings,
            "structured_json": json.dumps(structured_data, ensure_ascii=False, indent=2),
            "uploaded": False,
            "technician": technician,
            "existing_diagram_ids": [
                int(item["id"]) for item in existing_diagrams if str(item.get("id", "")).isdigit()
            ],
        }
        preview = _preview_from_download(token, drawio_stores.downloads[token])
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
        client = GlpiClient.from_environment()
        if not client:
            return Response("GLPI no esta configurado.", status=503, mimetype="text/plain; charset=utf-8")
        try:
            entity_id = positive_integer(payload.get("entity_id"), "entity_id")
            technician = payload.get("technician") or current_technician()
            with client.batch_session():
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
                diagram_id, diagram_url = publish_diagram(
                    client,
                    drawio_stores,
                    entity_id=entity_id,
                    diagram_name=diagram_name,
                    client_name=payload["cliente"],
                    site_name=payload["sede"],
                    technician=technician,
                    source="Generado",
                    graph_xml=payload["xml"],
                    filename=payload.get("filename", ""),
                )
        except ValueError as exc:
            return Response(
                public_error_message(str(exc), context="publicacion en GLPI"),
                status=400,
                mimetype="text/plain; charset=utf-8",
            )
        except GlpiError as exc:
            security_logger.warning(f"GLPI confirm failed: {exc} (IP: {get_remote_address()})")
            return Response(
                public_error_message(str(exc), context="publicacion en GLPI"),
                status=502,
                mimetype="text/plain; charset=utf-8",
            )
        drawio_stores.downloads.update_payload(token, uploaded=True)
        return jsonify({"id": diagram_id, "url": diagram_url})

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
        work_order_id = str(payload.get("work_order_id") or request.form.get("work_order_id") or "").strip()
        products_text = str(payload.get("products_text") or request.form.get("products_text") or "").strip()
        try:
            if pasted_text:
                result = parse_work_order_paste(pasted_text)
            elif products_text and not url and not work_order_id:
                result = import_products_text(products_text)
            elif work_order_id or url:
                result = import_work_order_by_id(work_order_id or url)
            else:
                raise CommsError(
                    "Pega el texto de la OT, indica un work order ID (ej. 7885 / OT00007885) "
                    "o un enlace de comms."
                )
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
                    "glpi_entity_id": result.glpi_entity_id or glpi_merge.get("glpi_entity_id") or "",
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

    @bp.get("/upload-draw/site-diagrams")
    @login_required
    @limiter.limit("120 per hour")
    def upload_draw_site_diagrams():
        entity_id_raw = request.args.get("entity_id", "").strip()
        if not entity_id_raw:
            return jsonify({"error": "Indica una sede."}), 400
        try:
            entity_id = positive_integer(entity_id_raw, "entity_id")
        except ValueError:
            return jsonify({"error": "Sede no valida."}), 400
        client = GlpiClient.from_environment()
        if not client:
            return jsonify({"error": "GLPI no esta configurado."}), 503
        try:
            rows = glpi_diagram_rows(client, entity_id, get_drawio_stores().activity)
        except GlpiError as exc:
            return jsonify({"error": public_error_message(str(exc), context="consulta de diagramas")}), 502
        rows.sort(key=lambda item: item.get("created_label", ""), reverse=True)
        return jsonify(
            {
                "count": len(rows),
                "diagrams": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name", ""),
                        "created_label": item.get("created_label") or "Fecha desconocida",
                        "technician": item.get("technician") or "—",
                        "source": item.get("source") or "GLPI",
                        "url": item.get("url", ""),
                        "preview_url": url_for(
                            "diagrams.preview_glpi_diagram",
                            diagram_id=int(item["id"]),
                            next=url_for("glpi_import.upload_draw"),
                        ),
                    }
                    for item in rows
                    if str(item.get("id", "")).isdigit()
                ],
            }
        )

    @bp.get("/upload-draw/clientes_con_sedes_sin_diagrama.xlsx")
    @login_required
    @limiter.limit("10 per hour")
    def upload_draw_missing_sites_xlsx() -> Response:
        catalog, catalog_error = load_glpi_catalog()
        if not catalog:
            return Response(
                public_error_message(catalog_error, context="catalogo GLPI"),
                status=503,
                mimetype="text/plain; charset=utf-8",
            )
        client = GlpiClient.from_environment()
        if not client:
            return Response("GLPI no esta configurado.", status=503, mimetype="text/plain; charset=utf-8")
        try:
            covered = client.list_covered_entity_ids()
        except GlpiError as exc:
            return Response(
                public_error_message(str(exc), context="consulta de diagramas GLPI"),
                status=502,
                mimetype="text/plain; charset=utf-8",
            )
        rows = build_missing_sites_rows(catalog, covered)
        return Response(
            missing_sites_to_xlsx(rows),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{MISSING_SITES_EXPORT_FILENAME}"'},
        )

    @bp.get("/upload-draw/missing-sites.xlsx")
    @login_required
    def upload_draw_missing_sites_xlsx_legacy() -> Response:
        return redirect(url_for("glpi_import.upload_draw_missing_sites_xlsx"))

    @bp.route("/upload-draw", methods=["GET", "POST"])
    @login_required
    @limiter.limit("50 per hour")
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
            corrected_address = request.form.get("glpi_direccion", "").strip()
            uploaded_files = request.files.getlist("drawio_files")
            if not uploaded_files or not uploaded_files[0].filename:
                legacy_file = request.files.get("drawio_file")
                uploaded_files = [legacy_file] if legacy_file and legacy_file.filename else []
            client_ip = get_remote_address()
            technician_name = current_technician().get("name", "unknown")

            if not entity_id:
                upload_error = "Selecciona una sede de GLPI."
            elif not uploaded_files:
                upload_error = "Selecciona uno o varios archivos .drawio o .pdf."
            else:
                try:
                    validated_entity_id = positive_integer(entity_id, "glpi_entity_id")
                    client = GlpiClient.from_environment()
                    if not client:
                        raise GlpiError("GLPI no esta configurado.")
                    technician = current_technician()
                    technician_label = (
                        technician.get("name") or technician.get("username") or "desconocido"
                    )
                    # Una sola sesion GLPI para todas las operaciones de la subida.
                    with client.batch_session():
                        if corrected_address:
                            upload_errors.extend(
                                sync_entity_address(
                                    client,
                                    drawio_stores,
                                    entity_id=validated_entity_id,
                                    address=corrected_address,
                                    glpi_customers=glpi_customers,
                                    technician_label=technician_label,
                                )
                            )
                        results, file_errors = publish_uploaded_files(
                            client,
                            drawio_stores,
                            uploaded_files,
                            entity_id=validated_entity_id,
                            client_name=client_name,
                            site_name=site_name,
                            technician=technician,
                            technician_name=technician_name,
                            client_ip=client_ip,
                        )
                    upload_results.extend(results)
                    upload_errors.extend(file_errors)
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
            site_diagrams_url=url_for("glpi_import.upload_draw_site_diagrams"),
            missing_sites_xlsx_url=url_for("glpi_import.upload_draw_missing_sites_xlsx"),
        )

    return bp
