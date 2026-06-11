from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .drawio_writer import BuildResult, build_drawio
from .layout_engine import build_layout, validate_input_data
from .library_loader import load_library
from .parser import infer_template, parse_equipment_line, parse_natural_text


REQUIRED_FIELDS = ("cliente", "sede", "direccion")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class WebGenerationResult:
    result: BuildResult
    data: dict
    filename: str
    total_equipment: int


def _clean_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _parse_router_ip(router_text: str, current_ip: str = "") -> tuple[str, str]:
    text = _clean_text(router_text)
    if not text:
        return "", current_ip
    if " - " in text:
        model, ip = text.split(" - ", 1)
        return model.strip(), ip.strip()
    return text, current_ip


def _parse_equipment_block(text: str) -> list[dict]:
    equipos: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("*") or line.startswith("-"):
            line = line[1:].strip()
        equipment = parse_equipment_line(line)
        if equipment:
            equipos.append(equipment)
    return equipos


def sanitize_filename(cliente: str, sede: str) -> str:
    base = f"{_clean_text(cliente)}_{_clean_text(sede)}"
    normalized = re.sub(r"\s+", "_", base)
    normalized = re.sub(r"[^A-Za-z0-9._-]", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("._")
    return f"{normalized or 'drawio_output'}.drawio"


def form_to_data(form: dict) -> dict:
    raw_text = _clean_text(form.get("raw_text"))
    data = parse_natural_text(raw_text) if raw_text else {"internet": {}, "ont": {}, "router": {}, "equipos": []}

    data["cliente"] = _clean_text(form.get("cliente")) or data.get("cliente", "")
    data["cif"] = _clean_text(form.get("cif")) or data.get("cif", "")
    data["sede"] = _clean_text(form.get("sede")) or data.get("sede", "")
    data["direccion"] = _clean_text(form.get("direccion")) or data.get("direccion", "")

    internet = data.setdefault("internet", {})
    internet["tipo"] = _clean_text(form.get("internet_tipo")) or internet.get("tipo", "")
    internet["velocidad"] = _clean_text(form.get("internet_velocidad")) or internet.get("velocidad", "")

    ont = data.setdefault("ont", {})
    ont["modelo"] = _clean_text(form.get("ont_modelo")) or ont.get("modelo", "")

    router = data.setdefault("router", {})
    router["modelo"] = _clean_text(form.get("router_modelo")) or router.get("modelo", "")
    router["ip"] = _clean_text(form.get("router_ip")) or router.get("ip", "")

    merged_model, merged_ip = _parse_router_ip(router.get("modelo", ""), router.get("ip", ""))
    router["modelo"] = merged_model
    router["ip"] = merged_ip

    equipment_text = _clean_text(form.get("equipos_text"))
    if equipment_text:
        data["equipos"] = _parse_equipment_block(equipment_text)
    else:
        data.setdefault("equipos", [])

    infer_template(data)
    return data


def validate_web_data(data: dict) -> list[str]:
    errors = []
    for field in REQUIRED_FIELDS:
        if not _clean_text(data.get(field)):
            errors.append(f"El campo '{field}' es obligatorio.")
    return errors


def resolve_library_path(library_path: str | Path) -> Path:
    path = Path(library_path)
    if path.is_absolute():
        return path
    candidates = [
        Path.cwd() / path,
        PROJECT_ROOT / path,
        PROJECT_ROOT.parent / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def build_drawio_from_data(data: dict, library_path: str | Path) -> WebGenerationResult:
    errors = validate_web_data(data)
    if errors:
        raise ValueError("\n".join(errors))

    resolved_library = resolve_library_path(library_path)
    if not resolved_library.exists():
        raise FileNotFoundError("No se ha encontrado la libreria. Revisa la ruta.")

    library = load_library(resolved_library)
    warnings = validate_input_data(data)
    nodes, edges = build_layout(data)
    result = build_drawio(nodes, edges, library, warnings=warnings)
    total_equipment = sum(int(team.get("cantidad", 1)) for team in data.get("equipos", []))
    return WebGenerationResult(
        result=result,
        data=data,
        filename=sanitize_filename(data.get("cliente", ""), data.get("sede", "")),
        total_equipment=total_equipment,
    )
