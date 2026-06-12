from __future__ import annotations

import json
import os
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from flask import Flask, Response, render_template, request, url_for

from generator.glpi_client import GlpiClient, GlpiError, build_customer_catalog
from generator.knowledge_base import learn_from_drawio
from generator.web_adapter import build_drawio_from_data, form_to_data, form_to_structured_data


DOWNLOADS: dict[str, dict] = {}
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = os.environ.get("DRAWIO_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("DRAWIO_PORT", os.environ.get("PORT", "8000")))


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"), static_folder=str(PROJECT_ROOT / "static"))
    app.config["DEFAULT_LIBRARY"] = "libreria_Ausarta_JUN_2026.xml"

    def load_glpi_catalog() -> tuple[list[dict], str]:
        client = GlpiClient.from_environment()
        if not client:
            return [], "GLPI no esta configurado."
        try:
            return build_customer_catalog(client.list_entities()), ""
        except GlpiError as exc:
            return [], str(exc)

    @app.get("/")
    def index() -> str:
        glpi_customers, glpi_error = load_glpi_catalog()
        return render_template(
            "index.html",
            form_data={"library_path": app.config["DEFAULT_LIBRARY"]},
            glpi_customers=glpi_customers,
            glpi_error=glpi_error,
        )

    @app.route("/upload-draw", methods=["GET", "POST"])
    def upload_draw() -> str:
        glpi_customers, glpi_error = load_glpi_catalog()
        upload_error = ""
        upload_result = None
        if request.method == "POST":
            entity_id = request.form.get("glpi_entity_id", "").strip()
            client_name = request.form.get("glpi_cliente", "").strip()
            site_name = request.form.get("glpi_sede", "").strip()
            uploaded_file = request.files.get("drawio_file")
            if not entity_id:
                upload_error = "Selecciona una sede de GLPI."
            elif not uploaded_file or not uploaded_file.filename:
                upload_error = "Selecciona un archivo .drawio."
            elif not uploaded_file.filename.lower().endswith((".drawio", ".xml")):
                upload_error = "El archivo debe tener extension .drawio o .xml."
            else:
                raw = uploaded_file.read()
                try:
                    xml = raw.decode("utf-8-sig")
                    root = ET.fromstring(xml)
                    if root.tag != "mxfile":
                        raise ValueError("El documento no contiene un mxfile de Draw.io.")
                    client = GlpiClient.from_environment()
                    if not client:
                        raise GlpiError("GLPI no esta configurado.")
                    diagram_id = client.create_network_diagram(
                        entity_id=int(entity_id),
                        name=Path(uploaded_file.filename).stem,
                        description=f"Diagrama historico de {client_name} - {site_name}",
                        graph_xml=xml,
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
                except (UnicodeDecodeError, ET.ParseError, ValueError, GlpiError) as exc:
                    upload_error = f"No se ha podido subir el diagrama: {exc}"
        return render_template(
            "upload_draw.html",
            glpi_customers=glpi_customers,
            glpi_error=glpi_error,
            upload_error=upload_error,
            upload_result=upload_result,
        )

    @app.post("/generate")
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
                form_data=form_data,
                errors=["No se ha encontrado la libreria. Revisa la ruta."],
                preview=None,
            ), 400
        except ValueError as exc:
            errors = [line for line in str(exc).splitlines() if line.strip()]
            return render_template("index.html", form_data=form_data, errors=errors, preview=None), 400

        glpi_entity_id = form_data.get("glpi_entity_id", "").strip()
        token = uuid.uuid4().hex
        DOWNLOADS[token] = {
            "filename": generated.filename,
            "xml": generated.result.xml,
            "entity_id": glpi_entity_id,
            "cliente": generated.data.get("cliente", ""),
            "sede": generated.data.get("sede", ""),
            "uploaded": False,
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
        }
        return render_template(
            "index.html",
            form_data=form_data,
            preview=preview,
            errors=[],
            glpi_customers=[],
            glpi_error="",
        )

    @app.get("/download/<token>")
    def download(token: str) -> Response:
        payload = DOWNLOADS.get(token)
        if not payload:
            return Response("Archivo no encontrado.", status=404, mimetype="text/plain; charset=utf-8")
        return Response(
            payload["xml"],
            mimetype="application/xml; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{payload["filename"]}"'},
        )

    @app.post("/confirm-glpi/<token>")
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
            diagram_id = client.create_network_diagram(
                entity_id=int(payload["entity_id"]),
                name=f"{payload['cliente']} - {payload['sede']}",
                description=f"Diagrama de red generado para {payload['cliente']}",
                graph_xml=payload["xml"],
            )
        except (GlpiError, ValueError) as exc:
            return Response(str(exc), status=502, mimetype="text/plain; charset=utf-8")
        payload["uploaded"] = True
        return Response(
            json.dumps({"id": diagram_id, "url": client.diagram_url(diagram_id)}),
            mimetype="application/json",
        )

    return app


if __name__ == "__main__":
    create_app().run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=False)
