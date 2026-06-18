from __future__ import annotations
import sqlite3
import time
from pathlib import Path


class SecurityLog:
    def __init__(self, db_path: str | Path):
        self._db = Path(db_path)
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS security_events (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts        INTEGER NOT NULL,
                    level     TEXT NOT NULL,
                    message   TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ts ON security_events (ts DESC)"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def write(self, level: str, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO security_events (ts, level, message) VALUES (?, ?, ?)",
                (int(time.time()), level.upper(), message),
            )

    def recent(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ts, level, message FROM security_events ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def purge_old(self, days: int = 30) -> None:
        cutoff = int(time.time()) - days * 86400
        with self._connect() as conn:
            conn.execute("DELETE FROM security_events WHERE ts < ?", (cutoff,))
