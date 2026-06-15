from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path


class CatalogCache:
    def __init__(self, path: str | Path, ttl_seconds: int = 300) -> None:
        self.path = Path(path)
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS catalog_cache (
                        cache_key TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at REAL NOT NULL,
                        expires_at REAL NOT NULL
                    )
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def get(self, key: str) -> list[dict] | None:
        now = time.time()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM catalog_cache WHERE cache_key = ? AND expires_at > ?",
                (key, now),
            ).fetchone()
            if not row:
                with connection:
                    connection.execute(
                        "DELETE FROM catalog_cache WHERE cache_key = ? AND expires_at <= ?",
                        (key, now),
                    )
                return None
        payload = json.loads(row[0])
        return payload if isinstance(payload, list) else None

    def set(self, key: str, payload: list[dict]) -> None:
        now = time.time()
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO catalog_cache (cache_key, payload, updated_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at
                    """,
                    (
                        key,
                        json.dumps(payload, ensure_ascii=False),
                        now,
                        now + self.ttl_seconds,
                    ),
                )

    def clear(self, key: str = "glpi_customer_catalog") -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM catalog_cache WHERE cache_key = ?", (key,))
