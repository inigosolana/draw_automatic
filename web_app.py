from __future__ import annotations

import uuid
from pathlib import Path

from flask import Flask, Response, render_template, request, url_for

from generator.web_adapter import build_drawio_from_data, form_to_data


DOWNLOADS: dict[str, tuple[str, str]] = {}
PROJECT_ROOT = Path(__file__).resolve().parent


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"), static_folder=str(PROJECT_ROOT / "static"))
    app.config["DEFAULT_LIBRARY"] = "libreria_Ausarta_JUN_2026.xml"

    @app.get("/")
    def index() -> str:
        return render_template("index.html", form_data={"library_path": app.config["DEFAULT_LIBRARY"]})

    @app.post("/generate")
    def generate() -> str:
        form_data = request.form.to_dict()
        form_data.setdefault("library_path", app.config["DEFAULT_LIBRARY"])
        try:
            data = form_to_data(form_data)
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

        token = uuid.uuid4().hex
        DOWNLOADS[token] = (generated.filename, generated.result.xml)
        preview = {
            "cliente": generated.data.get("cliente", ""),
            "sede": generated.data.get("sede", ""),
            "direccion": generated.data.get("direccion", ""),
            "template": generated.data.get("template", ""),
            "total_equipment": generated.total_equipment,
            "warnings": generated.result.warnings,
            "download_url": url_for("download", token=token),
            "filename": generated.filename,
        }
        return render_template("index.html", form_data=form_data, preview=preview, errors=[])

    @app.get("/download/<token>")
    def download(token: str) -> Response:
        payload = DOWNLOADS.get(token)
        if not payload:
            return Response("Archivo no encontrado.", status=404, mimetype="text/plain; charset=utf-8")
        filename, xml = payload
        return Response(
            xml,
            mimetype="application/xml; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8000, debug=False)
