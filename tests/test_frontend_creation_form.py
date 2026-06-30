"""Verificación del frontend del formulario de creación (creation-form*.js).

Renderiza el HTML real de /draw y ejecuta los módulos JS en jsdom (vía Node) para
comprobar que conectividad, plantillas, terminales, importación de OT y reset
siguen funcionando tras cambios en el JS.

Requiere Node y jsdom (instalar con `npm install` en tests/frontend/). Si no están
disponibles, el test se SALTA en vez de fallar — así la suite Python no depende de
tener un entorno Node.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app_factory import build_drawio_stores, create_app

FRONTEND_DIR = Path(__file__).parent / "frontend"
HARNESS = FRONTEND_DIR / "creation_form_harness.js"
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


def _render_draw_html() -> str:
    tmp = tempfile.mkdtemp()
    for key in ("DOWNLOAD", "SITE", "CATALOG", "ACTIVITY", "SECLOG", "TEMPLATE", "LEARNING"):
        os.environ[f"DRAWIO_{key}_DB"] = os.path.join(tmp, f"{key.lower()}.sqlite3")
    os.environ["DRAWIO_RATELIMIT_STORAGE"] = "memory://"
    os.environ.setdefault("DRAWIO_SECRET_KEY", "test-secret-for-frontend-harness")
    app = create_app(build_drawio_stores(Path(tmp)))
    app.config["AUTH_REQUIRED"] = False
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client().get("/draw").get_data(as_text=True)


class CreationFormFrontendTests(unittest.TestCase):
    def test_creation_form_modules_work_in_jsdom(self) -> None:
        node = _node_with_jsdom()
        if not node:
            self.skipTest("Node o jsdom no disponibles (npm install en tests/frontend/).")

        html = _render_draw_html()
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
            fh.write(html)
            html_path = fh.name
        try:
            result = subprocess.run(
                [node, str(HARNESS)],
                cwd=str(FRONTEND_DIR),
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "CREATION_FORM_HTML": html_path, "CREATION_FORM_JS_DIR": str(JS_DIR)},
            )
        finally:
            os.unlink(html_path)

        self.assertEqual(
            result.returncode,
            0,
            msg=f"El arnés jsdom reportó fallos:\n{result.stdout}\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
