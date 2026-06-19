from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path


class DiagramActivity:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS diagram_activity (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        diagram_id INTEGER NOT NULL,
                        entity_id INTEGER NOT NULL,
                        diagram_name TEXT NOT NULL,
                        client_name TEXT NOT NULL,
                        site_name TEXT NOT NULL,
                        technician_username TEXT NOT NULL,
                        technician_name TEXT NOT NULL,
                        source TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_diagram_activity_technician
                    ON diagram_activity (technician_username, created_at DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_diagram_activity_entity
                    ON diagram_activity (entity_id, created_at DESC)
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def add(
        self,
        *,
        diagram_id: int,
        entity_id: int,
        diagram_name: str,
        client_name: str,
        site_name: str,
        technician: dict,
        source: str,
    ) -> None:
        username = str(technician.get("username") or technician.get("name") or "local").strip()
        name = str(technician.get("name") or username).strip()
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO diagram_activity (
                        diagram_id, entity_id, diagram_name, client_name, site_name,
                        technician_username, technician_name, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(diagram_id),
                        int(entity_id),
                        diagram_name,
                        client_name,
                        site_name,
                        username,
                        name,
                        source,
                        time.time(),
                    ),
                )

    def list_for_entity(self, entity_id: int, limit: int = 250) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT diagram_id, entity_id, diagram_name, client_name, site_name,
                       technician_username, technician_name, source, created_at
                FROM diagram_activity
                WHERE entity_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (int(entity_id), max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def map_for_entity(self, entity_id: int) -> dict[int, dict]:
        return {row["diagram_id"]: row for row in self.list_for_entity(entity_id)}

    def list_for_technician(self, username: str, limit: int = 250) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT diagram_id, entity_id, diagram_name, client_name, site_name,
                       technician_name, source, created_at
                FROM diagram_activity
                WHERE technician_username = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (str(username).strip(), max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_all(self) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM diagram_activity ORDER BY created_at DESC LIMIT 1000
                """
            ).fetchall()
        return [dict(r) for r in rows]
