from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path


class SiteDirectory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS site_addresses (
                        entity_id INTEGER PRIMARY KEY,
                        address TEXT NOT NULL,
                        updated_by TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def get(self, entity_id: int) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT address, updated_by, updated_at FROM site_addresses WHERE entity_id = ?",
                (int(entity_id),),
            ).fetchone()
        if not row:
            return None
        return {"address": row[0], "updated_by": row[1], "updated_at": row[2]}

    def set(self, entity_id: int, address: str, updated_by: str) -> None:
        from .address_formatter import normalize_street_address

        clean_address = normalize_street_address(address)
        if not clean_address:
            return
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO site_addresses (entity_id, address, updated_by, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(entity_id) DO UPDATE SET
                        address = excluded.address,
                        updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (int(entity_id), clean_address, updated_by, time.time()),
                )

    def all(self) -> dict[int, dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT entity_id, address, updated_by, updated_at FROM site_addresses"
            ).fetchall()
        return {
            int(row[0]): {"address": row[1], "updated_by": row[2], "updated_at": row[3]}
            for row in rows
        }


def apply_saved_addresses(catalog: list[dict], saved: dict[int, dict]) -> list[dict]:
    for province in catalog:
        for customer in province.get("clientes", []):
            for site in customer.get("sedes", []):
                entity_id = site.get("id")
                if isinstance(entity_id, int) and entity_id in saved:
                    site["direccion_glpi"] = site.get("direccion", "")
                    site["direccion"] = saved[entity_id]["address"]
                    site["direccion_guardada"] = True
    return catalog
