from __future__ import annotations

from .aliases import resolve_alias
from .parser import ValidatedEquipment

DECT_BASE_MODELS = {"w60b", "w70b", "w80b", "w90b"}
DECT_HANDSET_MODELS = {"w71h", "w72h", "w53", "w53h", "w73h"}
DECT_HANDSET_BASE = {
    "w71h": "W60B",
    "w72h": "W60B",
    "w53": "W80B",
    "w53h": "W80B",
    "w73h": "YEALINK W90DM",
}


def _safe(value: object) -> str:
    return "" if value is None else str(value)


def _display_model(value: str) -> str:
    return resolve_alias(value or "")


def _normalized_model(team: dict) -> str:
    return _safe(team.get("modelo", team.get("tipo", ""))).strip().lower()


def _dect_handset_key(normalized_model: str) -> str | None:
    for handset in DECT_HANDSET_MODELS:
        if handset in normalized_model:
            return handset
    return None


def _dect_base_model(normalized_model: str) -> str:
    handset_key = _dect_handset_key(normalized_model)
    if handset_key:
        return DECT_HANDSET_BASE.get(handset_key, "W60B")
    return "W60B"


def _resolve_dect_base(team: dict, normalized_model: str) -> str:
    custom = _safe(team.get("dect_base", "")).strip()
    if custom:
        return _display_model(custom)
    return _dect_base_model(normalized_model)


def _is_dect_base(normalized_model: str) -> bool:
    return any(base in normalized_model for base in DECT_BASE_MODELS)


def _dect_registry_key(team: dict, normalized_model: str) -> str:
    custom = _safe(team.get("dect_base", "")).strip()
    if custom:
        return _display_model(custom).upper()
    return _display_model(_dect_base_model(normalized_model)).upper()


def _max_dect_stack_depth(equipos: list) -> int:
    counts: dict[str, int] = {}
    for index, team in enumerate(equipos):
        if team.get("tipo") == "switch":
            continue
        normalized = _normalized_model(team)
        if not _dect_handset_key(normalized):
            continue
        validated = ValidatedEquipment.from_dict(team, index)
        key = _dect_registry_key(team, normalized)
        counts[key] = counts.get(key, 0) + validated.cantidad
    return max(counts.values(), default=1)


def count_dect_handsets_per_base(equipos: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for index, team in enumerate(equipos):
        if team.get("tipo") == "switch":
            continue
        normalized = _normalized_model(team)
        if not _dect_handset_key(normalized):
            continue
        validated = ValidatedEquipment.from_dict(team, index)
        key = _dect_registry_key(team, normalized)
        counts[key] = counts.get(key, 0) + validated.cantidad
    return counts
