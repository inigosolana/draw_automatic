"""Gate ESLint no-undef sobre TODO el JS de front (static/js).

La regla `no-undef` caza variables usadas fuera de su ámbito — p. ej. una const
definida en un IIFE y usada en otro (el fallo que dejaba la subida a GLPI colgada
en "Subiendo…" para siempre, porque `runUpload` referenciaba `config`, que vivía
en el otro IIFE del mismo fichero). Este test cubre de golpe TODOS los .js, ahora
y en el futuro, que es lo que un test por fichero no garantiza.

Requiere Node y ESLint (instalar con `npm install` en tests/frontend/). Si no
están, el test se SALTA — la suite Python no depende de tener entorno Node.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "tests" / "frontend"
ESLINT_BIN = FRONTEND_DIR / "node_modules" / ".bin" / "eslint"
CONFIG = ROOT / "eslint.config.mjs"


def _eslint() -> str | None:
    if not shutil.which("node"):
        return None
    # En Windows el binario real es eslint.cmd / eslint.ps1; probamos ambos.
    for candidate in (ESLINT_BIN, ESLINT_BIN.with_suffix(".cmd")):
        if candidate.exists():
            return str(candidate)
    return None


class FrontendEslintTests(unittest.TestCase):
    def test_no_undefined_variables_in_static_js(self) -> None:
        eslint = _eslint()
        if not eslint or not CONFIG.exists():
            self.skipTest("Node o ESLint no disponibles (npm install en tests/frontend/).")
        result = subprocess.run(
            [eslint, "static/js/*.js", "--no-warn-ignored"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg="ESLint no-undef encontró variables fuera de ámbito:\n"
            + (result.stdout or "") + (result.stderr or ""),
        )


if __name__ == "__main__":
    unittest.main()
