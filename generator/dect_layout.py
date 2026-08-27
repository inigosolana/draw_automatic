from __future__ import annotations

import re

from .aliases import resolve_alias
from .parser import ValidatedEquipment

# Cuando una sede tiene VARIAS bases del mismo modelo (dos W70B, por ejemplo)
# hay que poder referirse a cada unidad fisica por separado: la clave de
# agrupacion lleva sufijo ("W70B-1", "W70B-2"). Sin el, las dos bases
# compartian clave, la segunda sobreescribia a la primera en el registro y
# TODOS los inalambricos acababan colgados de una sola, dejando la otra vacia.
DECT_BASE_SUFFIX_RE = re.compile(r"\s*[-#]\s*(\d+)\s*$")

DECT_BASE_MODELS = {"w60b", "w70b", "w80b", "w90b", "w90dm"}
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


def strip_dect_base_suffix(value: str) -> str:
    """Quita el "-1"/"-2" de una clave de base y deja el modelo dibujable.

    La clave agrupa ("W70B-2"); el modelo es lo que se pinta y lo que busca el
    icono en la libreria ("W70B"), asi que nunca puede llevar el sufijo.
    """
    return DECT_BASE_SUFFIX_RE.sub("", _safe(value)).strip()


def dect_base_unit_label(base_model: str, index: int, total: int) -> str:
    """Clave de una base concreta: con una sola no se numera, con varias si."""
    model = strip_dect_base_suffix(base_model)
    if total <= 1:
        return model
    return f"{model}-{index + 1}"


def _resolve_dect_base(team: dict, normalized_model: str) -> str:
    custom = _safe(team.get("dect_base", "")).strip()
    if custom:
        return _display_model(strip_dect_base_suffix(custom))
    return _dect_base_model(normalized_model)


def _is_dect_base(normalized_model: str) -> bool:
    return any(base in normalized_model for base in DECT_BASE_MODELS)


def physical_base_registry_key(team: dict) -> str:
    """Clave con la que se registra (y deduplica) una base DECT fisica.

    Por defecto es su modelo, como siempre. Pero si la base trae una clave de
    unidad ("W70B-2") se usa esa: es lo que permite dibujar DOS bases del mismo
    modelo y que cada inalambrico encuentre la suya. Sin sufijo el
    comportamiento es el de antes, para no mover los diagramas existentes.
    """
    custom = _safe(team.get("dect_base", "")).strip()
    if DECT_BASE_SUFFIX_RE.search(custom):
        return _dect_registry_key(team, _normalized_model(team))
    return _display_model(_safe(team.get("modelo"))).upper()


def _dect_registry_key(team: dict, normalized_model: str) -> str:
    custom = _safe(team.get("dect_base", "")).strip()
    if custom:
        # El sufijo de unidad SI forma parte de la clave (es lo que separa la
        # base 1 de la base 2); el alias se resuelve sobre el modelo pelado.
        key = _display_model(strip_dect_base_suffix(custom)).upper()
        unit = DECT_BASE_SUFFIX_RE.search(custom)
        return f"{key}-{unit.group(1)}" if unit else key
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
