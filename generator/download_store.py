from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator, MutableMapping
from contextlib import closing
from pathlib import Path


class DownloadStore(MutableMapping[str, dict]):
    def __init__(self, path: str | Path, ttl_seconds: int = 86400) -> None:
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS downloads (
                        token TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        expires_at REAL NOT NULL
                    )
                    """
                )

    def cleanup(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM downloads WHERE expires_at <= ?", (time.time(),))

    def __getitem__(self, token: str) -> dict:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM downloads WHERE token = ?",
                (token,),
            ).fetchone()
        if not row:
            raise KeyError(token)
        return json.loads(row[0])

    def __setitem__(self, token: str, payload: dict) -> None:
        now = time.time()
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO downloads (token, payload, created_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (token, json.dumps(payload, ensure_ascii=False), now, now + self.ttl_seconds),
                )

    def __delitem__(self, token: str) -> None:
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute("DELETE FROM downloads WHERE token = ?", (token,))
        if not cursor.rowcount:
            raise KeyError(token)

    def __iter__(self) -> Iterator[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT token FROM downloads ORDER BY created_at").fetchall()
        return iter(row[0] for row in rows)

    def __len__(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT COUNT(*) FROM downloads").fetchone()
        return int(row[0])

    def clear(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM downloads")

    def update_payload(self, token: str, **changes: object) -> dict:
        payload = self[token]
        payload.update(changes)
        self[token] = payload
        return payload
