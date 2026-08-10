"""Aprendizaje de conectividad a partir de lo que generan los técnicos.

Registra los valores de conectividad de cada diagrama generado y, sobre ese
historial, ofrece tres ayudas en el formulario de "Crear diagrama":

1. **Sugerencias de valores frecuentes** por campo (con preferencia por los más
   usados con el mismo proveedor/tipo de internet).
2. **Aprendizaje de correcciones**: cuando un técnico cambia un valor
   autorrellenado (de una plantilla o de una OT importada) antes de generar,
   guarda la corrección y la usa para avisar "esto suele cambiarse por X".
3. **Aviso de combinaciones poco habituales**: si dos valores conocidos casi
   nunca se han visto juntos, lo señala como posible error.

Diseñado para no romper nunca la generación: cualquier fallo de E/S se traga y
degrada a "sin sugerencias". Solo guarda valores de conectividad, nunca datos de
la sede (cliente/sede/dirección).
"""

from __future__ import annotations

import random
import sqlite3
import time
from contextlib import closing
from pathlib import Path

# Retención del historial de aprendizaje: se podan filas más antiguas que esto
# (probabilísticamente al insertar) para que las tablas no crezcan sin fin.
RETENTION_DAYS = 365

# Campos de conectividad que aprendemos. router_ip se registra pero NO se sugiere
# (es casi único por sede, no tiene sentido como autocompletado).
LEARNED_FIELDS = (
    "internet_tipo",
    "internet_velocidad",
    "internet_proveedor",
    "ont_modelo",
    "router_modelo",
    "backup_modelo",
    "router_ip",
)
SUGGEST_FIELDS = tuple(f for f in LEARNED_FIELDS if f != "router_ip")

# Pares de campos cuya co-ocurrencia vigilamos para avisar de combinaciones raras.
_COMBINATION_PAIRS = (
    ("internet_tipo", "internet_proveedor"),
    ("internet_tipo", "backup_modelo"),
    ("internet_proveedor", "ont_modelo"),
    ("internet_proveedor", "router_modelo"),
)

# Umbrales para no dar la lata en frío (pocos datos => sin avisos).
_MIN_OBSERVATIONS_FOR_COMBOS = 25
_MIN_VALUE_SEEN_FOR_COMBOS = 5
_MIN_CORRECTIONS_TO_FLAG = 3


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


class ConnectivityLearning:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        technician TEXT NOT NULL DEFAULT '',
                        internet_tipo TEXT NOT NULL DEFAULT '',
                        internet_velocidad TEXT NOT NULL DEFAULT '',
                        internet_proveedor TEXT NOT NULL DEFAULT '',
                        ont_modelo TEXT NOT NULL DEFAULT '',
                        router_modelo TEXT NOT NULL DEFAULT '',
                        backup_modelo TEXT NOT NULL DEFAULT '',
                        router_ip TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS corrections (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        field TEXT NOT NULL,
                        from_value TEXT NOT NULL,
                        to_value TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_corr_field ON corrections(field, from_value)"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    # -- escritura --------------------------------------------------------

    def record(self, payload: dict, technician: str = "") -> None:
        """Registra los valores de conectividad de un diagrama generado."""
        values = {field: _norm(payload.get(field)) for field in LEARNED_FIELDS}
        # No registramos observaciones totalmente vacías (no aportan nada).
        if not any(values[f] for f in SUGGEST_FIELDS):
            return
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        f"""
                        INSERT INTO observations
                            (ts, technician, {", ".join(LEARNED_FIELDS)})
                        VALUES (?, ?, {", ".join("?" for _ in LEARNED_FIELDS)})
                        """,
                        (time.time(), _norm(technician), *(values[f] for f in LEARNED_FIELDS)),
                    )
                    self._maybe_prune(connection)
        except sqlite3.Error:
            pass

    def _maybe_prune(self, connection: sqlite3.Connection) -> None:
        """Poda (probabilística) filas más antiguas que RETENTION_DAYS."""
        if random.random() >= 0.02:
            return
        cutoff = time.time() - RETENTION_DAYS * 86400
        for table in ("observations", "corrections"):
            try:
                connection.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))
            except sqlite3.Error:
                pass

    def record_corrections(self, baseline: dict, final: dict) -> None:
        """Guarda los campos que el técnico cambió respecto a lo autorrellenado."""
        rows = []
        for field in SUGGEST_FIELDS:
            before = _norm(baseline.get(field))
            after = _norm(final.get(field))
            if before and after and before != after:
                rows.append((time.time(), field, before, after))
        if not rows:
            return
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.executemany(
                        "INSERT INTO corrections (ts, field, from_value, to_value) VALUES (?, ?, ?, ?)",
                        rows,
                    )
        except sqlite3.Error:
            pass

    # -- lectura ----------------------------------------------------------

    def _count(self, connection: sqlite3.Connection) -> int:
        return int(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0])

    def suggestions(self, proveedor: str = "", tipo: str = "", limit: int = 8) -> dict:
        """Valores más usados por campo, priorizando el mismo proveedor/tipo."""
        proveedor = _norm(proveedor)
        tipo = _norm(tipo)
        result: dict[str, list[str]] = {}
        try:
            with closing(self._connect()) as connection:
                for field in SUGGEST_FIELDS:
                    ranked: list[str] = []
                    seen: set[str] = set()
                    # 1) los más usados en el mismo contexto (proveedor/tipo).
                    if proveedor or tipo:
                        clauses, params = [], []
                        if proveedor:
                            clauses.append("internet_proveedor = ?")
                            params.append(proveedor)
                        if tipo:
                            clauses.append("internet_tipo = ?")
                            params.append(tipo)
                        where = " AND ".join(clauses)
                        for (value, _count) in connection.execute(
                            f"""
                            SELECT {field}, COUNT(*) c FROM observations
                            WHERE {where} AND {field} != ''
                            GROUP BY {field} ORDER BY c DESC, {field} LIMIT ?
                            """,
                            (*params, limit),
                        ):
                            if value not in seen:
                                seen.add(value)
                                ranked.append(value)
                    # 2) completar con los más usados en general.
                    if len(ranked) < limit:
                        for (value, _count) in connection.execute(
                            f"""
                            SELECT {field}, COUNT(*) c FROM observations
                            WHERE {field} != ''
                            GROUP BY {field} ORDER BY c DESC, {field} LIMIT ?
                            """,
                            (limit,),
                        ):
                            if value not in seen:
                                seen.add(value)
                                ranked.append(value)
                    result[field] = ranked[:limit]
        except sqlite3.Error:
            return {field: [] for field in SUGGEST_FIELDS}
        return result

    def warnings(self, payload: dict) -> list[str]:
        """Avisos de combinaciones raras o valores que suelen corregirse."""
        values = {field: _norm(payload.get(field)) for field in LEARNED_FIELDS}
        messages: list[str] = []
        try:
            with closing(self._connect()) as connection:
                total = self._count(connection)
                messages.extend(self._combination_warnings(connection, values, total))
                messages.extend(self._correction_warnings(connection, values))
        except sqlite3.Error:
            return []
        # Sin duplicados, preservando orden.
        seen: set[str] = set()
        unique = []
        for msg in messages:
            if msg not in seen:
                seen.add(msg)
                unique.append(msg)
        return unique

    def _value_count(self, connection: sqlite3.Connection, field: str, value: str) -> int:
        # `field` se interpola en el SQL: debe ser SIEMPRE una columna conocida,
        # nunca input de usuario (evita inyección por identificador).
        if field not in LEARNED_FIELDS:
            raise ValueError(f"Campo no permitido: {field}")
        row = connection.execute(
            f"SELECT COUNT(*) FROM observations WHERE {field} = ?", (value,)
        ).fetchone()
        return int(row[0]) if row else 0

    def _combination_warnings(
        self, connection: sqlite3.Connection, values: dict, total: int
    ) -> list[str]:
        if total < _MIN_OBSERVATIONS_FOR_COMBOS:
            return []
        messages = []
        for field_a, field_b in _COMBINATION_PAIRS:
            val_a, val_b = values[field_a], values[field_b]
            if not val_a or not val_b:
                continue
            count_a = self._value_count(connection, field_a, val_a)
            count_b = self._value_count(connection, field_b, val_b)
            # Solo avisamos si ambos valores son conocidos por separado…
            if count_a < _MIN_VALUE_SEEN_FOR_COMBOS or count_b < _MIN_VALUE_SEEN_FOR_COMBOS:
                continue
            together = connection.execute(
                f"SELECT COUNT(*) FROM observations WHERE {field_a} = ? AND {field_b} = ?",
                (val_a, val_b),
            ).fetchone()[0]
            # …pero casi nunca se han visto juntos.
            if together == 0:
                messages.append(
                    f"Combinación poco habitual: «{val_a}» con «{val_b}» no se había usado junta antes. Revísalo."
                )
        return messages

    def _correction_warnings(self, connection: sqlite3.Connection, values: dict) -> list[str]:
        messages = []
        for field in SUGGEST_FIELDS:
            value = values[field]
            if not value:
                continue
            row = connection.execute(
                """
                SELECT to_value, COUNT(*) c FROM corrections
                WHERE field = ? AND from_value = ?
                GROUP BY to_value ORDER BY c DESC LIMIT 1
                """,
                (field, value),
            ).fetchone()
            if row and int(row[1]) >= _MIN_CORRECTIONS_TO_FLAG:
                messages.append(
                    f"«{value}» suele cambiarse por «{row[0]}» ({int(row[1])} veces). Confírmalo."
                )
        return messages
