from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def format_activity_timestamp(created_at: float) -> str:
    return datetime.fromtimestamp(created_at).strftime("%d/%m/%Y %H:%M")


def diagram_source_meta(source: str) -> dict[str, str]:
    normalized = (source or "").strip().lower()
    if normalized in {"draw subido", "archivo antiguo"}:
        return {
            "key": "subido",
            "label": "Subido",
            "description": "Archivo .drawio subido manualmente",
            "badge_class": "source-badge-upload",
        }
    if normalized == "version":
        return {
            "key": "version",
            "label": "Version",
            "description": "Copia guardada al editar un diagrama en GLPI",
            "badge_class": "source-badge-version",
        }
    return {
        "key": "generado",
        "label": "Generado",
        "description": "Creado desde la app draw.io",
        "badge_class": "source-badge-generated",
    }


def build_diagram_description(
    *,
    client_name: str,
    site_name: str,
    technician: dict,
    source: str,
    filename: str = "",
) -> str:
    tech = (technician.get("name") or technician.get("username") or "desconocido").strip()
    when = datetime.now().strftime("%d/%m/%Y %H:%M")
    parts = [source, when, tech, f"{client_name} - {site_name}"]
    if filename:
        parts.insert(1, Path(filename).name[:24])
    return " | ".join(parts)[:100]


def unique_diagram_name(base_name: str, existing_diagrams: list[dict]) -> str:
    base = base_name.strip()[:45]
    if not existing_diagrams:
        return base
    existing_names = {str(item.get("name", "")).strip().lower() for item in existing_diagrams}
    if base.lower() not in existing_names:
        return base
    stamp = datetime.now().strftime("%d%m%y-%H%M")
    trimmed = base[: max(1, 45 - len(stamp) - 1)].rstrip()
    return f"{trimmed} {stamp}"[:45]


_VERSION_SUFFIX_RE = re.compile(r"_\d{8}_\d{6}$")
_LEGACY_VERSION_SUFFIX_RE = re.compile(r" \d{6}\d{2}-\d{4}$")


def diagram_base_name(name: str) -> str:
    stem = Path(name).stem if name else ""
    stem = stem.strip()
    while stem:
        if _VERSION_SUFFIX_RE.search(stem):
            stem = _VERSION_SUFFIX_RE.sub("", stem)
            continue
        legacy = _LEGACY_VERSION_SUFFIX_RE.search(stem)
        if legacy:
            stem = stem[: legacy.start()].rstrip()
            continue
        break
    return stem.strip() or "diagrama"


def versioned_diagram_name(base_name: str, when: datetime | None = None) -> str:
    when = when or datetime.now()
    suffix = when.strftime("_%Y%m%d_%H%M%S")
    base = diagram_base_name(base_name)
    max_len = max(1, 45 - len(suffix))
    trimmed = base[:max_len].rstrip("_ ").strip()
    return f"{trimmed or 'diagrama'}{suffix}"


def versioned_drawio_filename(base_name: str, when: datetime | None = None) -> str:
    return f"{versioned_diagram_name(base_name, when=when)}.drawio"


def enrich_activity_rows(rows: list[dict], client) -> list[dict]:
    enriched: list[dict] = []
    for item in rows:
        row = dict(item)
        row["created_label"] = format_activity_timestamp(row["created_at"])
        row["technician"] = row.get("technician_name") or row.get("technician_username") or "—"
        diagram_id = row.get("diagram_id")
        row["url"] = client.diagram_url(int(diagram_id)) if client and diagram_id else ""
        source_meta = diagram_source_meta(row.get("source", ""))
        row["source_key"] = source_meta["key"]
        row["source_label"] = source_meta["label"]
        row["source_description"] = source_meta["description"]
        row["source_badge_class"] = source_meta["badge_class"]
        enriched.append(row)
    return enriched


def enrich_diagram_row(diagram: dict, activity_by_id: dict[int, dict]) -> dict:
    row = dict(diagram)
    activity = activity_by_id.get(int(row.get("id") or row.get("diagram_id") or 0))
    if activity:
        row["created_label"] = format_activity_timestamp(activity["created_at"])
        row["technician"] = activity.get("technician_name") or activity.get("technician_username") or ""
        row["source"] = activity.get("source") or ""
    else:
        row["created_label"] = ""
        row["technician"] = ""
        row["source"] = "GLPI"
    source_meta = diagram_source_meta(row.get("source", ""))
    row["source_key"] = source_meta["key"]
    row["source_label"] = source_meta["label"]
    row["source_description"] = source_meta["description"]
    row["source_badge_class"] = source_meta["badge_class"]
    return row
