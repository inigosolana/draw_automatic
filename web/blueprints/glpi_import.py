from __future__ import annotations

import json
import uuid

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app_context import (
    can_access_pending,
    current_technician,
    get_drawio_stores,
    login_required,
    security_logger,
    technician_label,
)
from web.services.glpi_catalog import glpi_diagram_rows, index_context, load_glpi_catalog, relevant_entity_ids
from generator.comms_client import CommsError, import_products_text
from generator.glpi_client import GlpiClient, GlpiError
from generator.work_order_import import import_work_order_by_id
from generator.diagram_metadata import unique_diagram_name
from generator.glpi_merge import merge_import_with_glpi, next_site_name
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
                security_logger.warning(
                    f"Diagrama pendiente no encontrado: token={pending} IP={get_remote_address()}"
                )
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
            library_path = form_data.get("library_path", current_app.config["DEFAULT_LIBRARY"])
            # El diagrama final SIEMPRE es el rico (iconos, etiquetas ETH, MAC/IP,
            # verde propio, tabla resumen). El editor de cajas es solo vista previa
            # orientativa y no se usa para generar (construir desde él perdía ese
            # detalle).
            generated = build_drawio_from_data(data, library_path)
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
                technician_label(technician),
            )
        token = uuid.uuid4().hex
        technician = current_technician()
        # Aprendizaje: registramos los valores de conectividad usados, aprendemos
        # de las correcciones sobre lo autorrellenado y añadimos avisos de
        # combinaciones poco habituales. Nunca debe romper la generación.
        learning_warnings: list[str] = []
        try:
            learning = drawio_stores.learning
            learning.record(form_data, technician.get("name") or technician.get("username") or "")
            baseline = json.loads(form_data.get("autofill_baseline") or "{}")
            if isinstance(baseline, dict) and baseline:
                learning.record_corrections(baseline, form_data)
            learning_warnings = learning.warnings(form_data)
        except (ValueError, TypeError, KeyError) as exc:
            security_logger.warning(f"Aprendizaje de conectividad fallo (no critico): {exc}")
            learning_warnings = []
        # Nota: los diagramas existentes de la sede los carga una sola vez
        # _preview_from_download() para mostrarlos. Antes se consultaban aquí
        # también (campo existing_diagram_ids que nadie leía), duplicando la
        # llamada a GLPI en cada generación.
        drawio_stores.downloads[token] = {
            "filename": generated.filename,
            "xml": generated.result.xml,
            "entity_id": glpi_entity_id,
            "cliente": generated.data.get("cliente", ""),
            "sede": generated.data.get("sede", ""),
            "direccion": generated.data.get("direccion", ""),
            "template": generated.data.get("template", ""),
            "total_equipment": generated.total_equipment,
            "warnings": [*generated.result.warnings, *learning_warnings],
            "structured_json": json.dumps(structured_data, ensure_ascii=False, indent=2),
            "uploaded": False,
            "technician": technician,
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
        if payload.get("uploaded"):
            return Response("El diagrama ya fue subido a GLPI.", status=409, mimetype="text/plain; charset=utf-8")
        if not can_access_pending(payload):
            return Response("No autorizado para este diagrama.", status=403, mimetype="text/plain; charset=utf-8")
        client = GlpiClient.from_environment()
        if not client:
            return Response("GLPI no esta configurado.", status=503, mimetype="text/plain; charset=utf-8")
        try:
            entity_id = positive_integer(payload.get("entity_id"), "entity_id")
            technician = payload.get("technician") or current_technician()
            with client.batch_session():
                # Duplicados: miramos la sede Y su entidad cliente (en GLPI casi
                # todos los diagramas cuelgan del cliente, no de la sede).
                catalog, _ = load_glpi_catalog(client)
                relevant = relevant_entity_ids(entity_id, catalog)
                existing = [
                    d
                    for d in client.list_network_diagrams(None)
                    if str(d.get("entities_id", "")).isdigit() and int(d["entities_id"]) in relevant
                ]
                # Diagrama ya en la MISMA sede: se versiona (actualiza + copia fechada).
                # Ordenamos por id descendente para versionar SIEMPRE el más reciente
                # (list_network_diagrams no garantiza orden por fecha).
                sede_existing = sorted(
                    (d for d in existing if str(d.get("entities_id")) == str(entity_id)),
                    key=lambda d: int(d["id"]) if str(d.get("id", "")).isdigit() else 0,
                    reverse=True,
                )
                allow_duplicate = request.form.get("allow_duplicate") == "1"
                if existing and not allow_duplicate:
                    msg = (
                        "Esta sede ya tiene un diagrama. Confirma para guardarlo como NUEVA VERSIÓN "
                        "(el diagrama actual se actualiza y se guarda una copia fechada)."
                        if sede_existing
                        else "Esta sede o su cliente ya tienen un diagrama en GLPI. Confirma de nuevo para publicar otro."
                    )
                    return Response(msg, status=409, mimetype="text/plain; charset=utf-8")

                if allow_duplicate and sede_existing:
                    # Versionar el diagrama existente de la sede con el contenido
                    # nuevo (que ya incluye lo fusionado). No duplica la sede.
                    diagram_id, diagram_name = client.save_network_diagram_version(
                        int(sede_existing[0]["id"]), payload["xml"], technician=technician
                    )
                    diagram_url = client.diagram_url(diagram_id)
                    drawio_stores.activity.add(
                        diagram_id=diagram_id,
                        entity_id=entity_id,
                        diagram_name=diagram_name,
                        client_name=payload["cliente"],
                        site_name=payload["sede"],
                        technician=technician,
                        source="Version",
                    )
                    try:
                        drawio_stores.catalog.clear("admin_coverage")
                    except Exception:  # noqa: BLE001 - invalidar caché nunca debe romper
                        pass
                else:
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

        # Si la OT resuelve una sede de GLPI, avisar de diagramas YA existentes de
        # esa sede/cliente para poder editarlos (añadir/quitar) en vez de duplicar.
        existing_diagrams: list[dict] = []
        entity_id_val = str(result.glpi_entity_id or glpi_merge.get("glpi_entity_id") or "").strip()
        if entity_id_val.isdigit():
            existing_client = GlpiClient.from_environment()
            if existing_client:
                try:
                    rows = glpi_diagram_rows(
                        existing_client,
                        relevant_entity_ids(int(entity_id_val), glpi_customers),
                        get_drawio_stores().activity,
                    )
                    existing_diagrams = [
                        {
                            "id": r["id"],
                            "name": r["name"],
                            "preview_url": url_for("diagrams.preview_glpi_diagram", diagram_id=r["id"]),
                            "as_form_url": url_for("diagrams.diagram_as_form", diagram_id=r["id"]),
                            "glpi_url": r.get("url", ""),
                        }
                        for r in rows[:10]
                    ]
                except GlpiError:
                    existing_diagrams = []
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
                    "glpi_client_id": glpi_merge.get("glpi_client_id") or "",
                    "sede_nueva": glpi_merge.get("sede_nueva", False),
                    "glpi_matched": glpi_merge.get("matched", False),
                    "glpi_confidence": glpi_merge.get("confidence", "none"),
                    "glpi_message": glpi_merge.get("message") or public_error_message(
                        glpi_error, context="sincronizacion GLPI"
                    ),
                    "glpi_corrections": glpi_merge.get("corrections") or [],
                    "glpi_suggestions": glpi_merge.get("suggestions") or [],
                    "existing_diagrams": existing_diagrams,
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

    @bp.post("/import-work-order/create-site")
    @login_required
    @limiter.limit("60 per hour")
    def create_glpi_site() -> Response:
        """Crea en GLPI una sede nueva bajo el cliente indicado (sede de la OT que
        GLPI no tenía). Devuelve el entity_id y nombre para seleccionarla."""
        payload = request.get_json(silent=True) or {}
        try:
            client_id = positive_integer(payload.get("client_id"), "client_id")
        except ValueError:
            return Response(
                json.dumps({"error": "Falta el cliente de GLPI para crear la sede."}, ensure_ascii=False),
                status=400, mimetype="application/json; charset=utf-8",
            )
        sede = str(payload.get("sede") or "").strip()
        direccion = str(payload.get("direccion") or "").strip()
        if not sede:
            return Response(
                json.dumps({"error": "Indica el nombre de la sede."}, ensure_ascii=False),
                status=400, mimetype="application/json; charset=utf-8",
            )
        client = GlpiClient.from_environment()
        if not client:
            return Response(
                json.dumps({"error": "GLPI no está configurado."}, ensure_ascii=False),
                status=503, mimetype="application/json; charset=utf-8",
            )
        catalog, _ = load_glpi_catalog(client)
        existing_names: list[str] = []
        for province in catalog or []:
            for customer in province.get("clientes") or []:
                if str(customer.get("id")) == str(client_id):
                    existing_names = [str(s.get("nombre") or "") for s in customer.get("sedes") or []]
                    break
        new_name = next_site_name(existing_names, sede)
        try:
            entity_id, created_name = client.create_site_entity(client_id, new_name, direccion)
        except GlpiError as exc:
            security_logger.warning(f"Create GLPI site failed: {exc} (IP: {get_remote_address()})")
            return Response(
                json.dumps({"error": public_error_message(str(exc), context="creación de la sede")}, ensure_ascii=False),
                status=502, mimetype="application/json; charset=utf-8",
            )
        try:
            get_drawio_stores().catalog.clear("admin_coverage")
            get_drawio_stores().catalog.clear("glpi_customer_catalog")
        except Exception:  # noqa: BLE001
            pass
        security_logger.info(
            f"GLPI site created: id={entity_id} name={created_name!r} under client={client_id} "
            f"(tech={technician_label()}, IP={get_remote_address()})"
        )
        return Response(
            json.dumps({"glpi_entity_id": entity_id, "sede": created_name}, ensure_ascii=False),
            mimetype="application/json; charset=utf-8",
        )

    @bp.post("/upload-draw/file")
    @login_required
    @limiter.limit("600 per hour")
    def upload_draw_file() -> Response:
        """Sube UN archivo y devuelve JSON (para la subida con progreso)."""
        entity_id_raw = request.form.get("glpi_entity_id", "").strip()
        client_name = request.form.get("glpi_cliente", "").strip()
        site_name = request.form.get("glpi_sede", "").strip()
        corrected_address = request.form.get("glpi_direccion", "").strip()
        apply_address = request.form.get("apply_address") == "1"
        uploaded_file = request.files.get("drawio_file")
        if not entity_id_raw:
            return jsonify({"ok": False, "error": "Selecciona una sede de GLPI."}), 400
        if not uploaded_file or not uploaded_file.filename:
            return jsonify({"ok": False, "error": "No se ha recibido el archivo."}), 400
        try:
            entity_id = positive_integer(entity_id_raw, "glpi_entity_id")
        except ValueError:
            return jsonify({"ok": False, "error": "Sede no valida."}), 400
        client = GlpiClient.from_environment()
        if not client:
            return jsonify({"ok": False, "error": "GLPI no esta configurado en el servidor. Avisa a sistemas."}), 503
        stores = get_drawio_stores()
        technician = current_technician()
        tech_label = technician_label(technician)
        warnings: list[str] = []
        try:
            with client.batch_session():
                if apply_address and corrected_address:
                    glpi_customers, _ = load_glpi_catalog()
                    warnings = sync_entity_address(
                        client, stores, entity_id=entity_id, address=corrected_address,
                        glpi_customers=glpi_customers, technician_label=tech_label,
                    )
                results, errors = publish_uploaded_files(
                    client, stores, [uploaded_file], entity_id=entity_id,
                    client_name=client_name, site_name=site_name, technician=technician,
                    technician_name=technician.get("name", "unknown"), client_ip=get_remote_address(),
                )
        except (ValueError, GlpiError) as exc:
            return jsonify({"ok": False, "error": public_error_message(str(exc), context="subida del diagrama")}), 502
        if results:
            r = results[0]
            return jsonify({"ok": True, "id": r["id"], "url": r["url"], "name": r["name"], "warnings": warnings})
        return jsonify({"ok": False, "error": errors[0] if errors else "No se ha podido subir el archivo.", "warnings": warnings})

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
        client = GlpiClient.from_environment()
        if not client:
            return Response("GLPI no esta configurado.", status=503, mimetype="text/plain; charset=utf-8")
        # Una sola sesión GLPI para el catálogo (si no está cacheado) y la
        # consulta de cobertura.
        try:
            with client.batch_session():
                catalog, catalog_error = load_glpi_catalog(client)
                if not catalog:
                    return Response(
                        public_error_message(catalog_error, context="catalogo GLPI"),
                        status=503,
                        mimetype="text/plain; charset=utf-8",
                    )
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
    # Limite alto: el flujo de subida en lote hace muchas peticiones (cada
    # subida y cada carga de pagina cuentan). 50/h era demasiado bajo.
    @limiter.limit("500 per hour")
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
                    tech_label = technician_label(technician)
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
                                    technician_label=tech_label,
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

    # -- Plantillas de conectividad (presets por tipo de instalación) -------

    def _json(payload: dict, status: int = 200) -> Response:
        return Response(
            json.dumps(payload, ensure_ascii=False),
            status=status,
            mimetype="application/json; charset=utf-8",
        )

    @bp.get("/api/templates")
    @login_required
    def templates_collection() -> Response:
        return _json({"templates": get_drawio_stores().templates.list_all()})

    @bp.post("/api/templates")
    @login_required
    @limiter.limit("60 per hour")
    def templates_create() -> Response:
        payload = request.get_json(silent=True) or {}
        technician = current_technician()
        updated_by = technician_label(technician)
        try:
            template_id = get_drawio_stores().templates.save(
                payload.get("name", ""), payload, updated_by
            )
        except ValueError as exc:
            return _json({"error": str(exc)}, status=400)
        return _json({"id": template_id})

    @bp.get("/api/templates/<int:template_id>")
    @login_required
    def templates_get(template_id: int) -> Response:
        template = get_drawio_stores().templates.get(template_id)
        if not template:
            return _json({"error": "La plantilla ya no existe."}, status=404)
        return _json(template)

    @bp.delete("/api/templates/<int:template_id>")
    @login_required
    def templates_delete(template_id: int) -> Response:
        get_drawio_stores().templates.delete(template_id)
        return _json({"ok": True})

    @bp.get("/api/connectivity/suggestions")
    @login_required
    def connectivity_suggestions() -> Response:
        learning = get_drawio_stores().learning
        proveedor = request.args.get("proveedor", "")
        tipo = request.args.get("tipo", "")
        return _json({"suggestions": learning.suggestions(proveedor=proveedor, tipo=tipo)})

    return bp
