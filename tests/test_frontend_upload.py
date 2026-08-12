"""Verificación del frontend de la subida a GLPI (upload-glpi-form.js).

Renderiza el HTML real de /upload-draw y ejecuta el JS en jsdom (vía Node) para
comprobar que, al elegir un archivo y una sede y enviar, se dispara la subida
(fetch a /upload-draw/file) sin lanzar excepción. Regresión del fallo en que
runUpload referenciaba `config` (de otro IIFE) y petaba antes del fetch.

Requiere Node y jsdom (npm install en tests/frontend/). Si no están, se SALTA.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app_factory import build_drawio_stores, create_app

FRONTEND_DIR = Path(__file__).parent / "frontend"
HARNESS = FRONTEND_DIR / "upload_form_harness.js"
JS_DIR = Path(__file__).parent.parent / "static" / "js"


def _node_with_jsdom() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    probe = subprocess.run(
        [node, "-e", "require.resolve('jsdom')"],
        cwd=str(FRONTEND_DIR),
        capture_output=True,
    )
    return node if probe.returncode == 0 else None


def _render_upload_html() -> str:
    tmp = tempfile.mkdtemp()
    for key in ("DOWNLOAD", "SITE", "CATALOG", "ACTIVITY", "SECLOG", "TEMPLATE", "LEARNING"):
        os.environ[f"DRAWIO_{key}_DB"] = os.path.join(tmp, f"{key.lower()}.sqlite3")
    os.environ["DRAWIO_RATELIMIT_STORAGE"] = "memory://"
    os.environ.setdefault("DRAWIO_SECRET_KEY", "test-secret-for-frontend-harness")
    app = create_app(build_drawio_stores(Path(tmp)))
    app.config["AUTH_REQUIRED"] = False
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client().get("/upload-draw").get_data(as_text=True)


class UploadFormFrontendTests(unittest.TestCase):
    def test_upload_form_triggers_fetch_in_jsdom(self) -> None:
        node = _node_with_jsdom()
        if not node:
            self.skipTest("Node o jsdom no disponibles (npm install en tests/frontend/).")
        if not HARNESS.exists():
            self.skipTest("Falta upload_form_harness.js.")

        html = _render_upload_html()
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
            fh.write(html)
            html_path = fh.name
        try:
            result = subprocess.run(
                [node, str(HARNESS)],
                cwd=str(FRONTEND_DIR),
                capture_output=True,
                text=True,
                env={**os.environ, "UPLOAD_FORM_HTML": html_path, "UPLOAD_FORM_JS_DIR": str(JS_DIR)},
                timeout=60,
            )
        finally:
            os.unlink(html_path)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
