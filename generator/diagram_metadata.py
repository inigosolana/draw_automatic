from __future__ import annotations

from datetime import datetime
from pathlib import Path


def format_activity_timestamp(created_at: float) -> str:
    return datetime.fromtimestamp(created_at).strftime("%d/%m/%Y %H:%M")


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
    return row
