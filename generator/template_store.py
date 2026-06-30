"""Plantillas de conectividad guardadas (presets por tipo de instalación).

Guardan los campos reutilizables de la pestaña Conectividad (tipo de internet,
velocidad, proveedor, ONT, router, backup, IP) para rellenar el formulario de
"Crear diagrama" en un clic. No guardan datos de la sede (cliente/sede/dirección).
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

# Campos de conectividad que componen una plantilla.
TEMPLATE_FIELDS = (
    "internet_tipo",
    "internet_velocidad",
    "internet_proveedor",
    "ont_modelo",
    "router_modelo",
    "backup_modelo",
    "router_ip",
)


class TemplateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS templates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        payload TEXT NOT NULL,
                        updated_by TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def list_all(self) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, name, updated_by, updated_at FROM templates ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [
            {"id": r[0], "name": r[1], "updated_by": r[2], "updated_at": r[3]} for r in rows
        ]

    def get(self, template_id: int) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT name, payload FROM templates WHERE id = ?", (int(template_id),)
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row[1])
        except (ValueError, TypeError):
            payload = {}
        return {"name": row[0], "payload": payload if isinstance(payload, dict) else {}}

    def save(self, name: str, payload: dict, updated_by: str) -> int:
        clean_name = " ".join(str(name or "").split()).strip()[:60]
        if not clean_name:
            raise ValueError("La plantilla necesita un nombre.")
        clean_payload = {k: str(payload.get(k, "") or "") for k in TEMPLATE_FIELDS}
        blob = json.dumps(clean_payload, ensure_ascii=False)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO templates (name, payload, updated_by, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        payload = excluded.payload,
                        updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (clean_name, blob, updated_by, time.time()),
                )
                row = connection.execute(
                    "SELECT id FROM templates WHERE name = ?", (clean_name,)
                ).fetchone()
        return int(row[0])

    def delete(self, template_id: int) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM templates WHERE id = ?", (int(template_id),))
