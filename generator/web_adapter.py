from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .aliases import resolve_alias
from .device_catalog import devices_json_to_equipos
from .drawio_writer import BuildResult, build_drawio
from .layout_engine import build_layout, validate_input_data
from .library_loader import load_library
from .parser import infer_template, parse_equipment_line, parse_natural_text


REQUIRED_FIELDS = ("cliente", "sede", "direccion")
ALLOWED_EQUIPMENT_TYPES = {
    "router",
    "switch",
    "telefono",
    "base_dect",
    "terminal_dect",
    "ata",
    "pc",
    "ont",
    "wifi",
    "otro",
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_NAME = "libreria_Ausarta_JUN_2026.xml"
BUNDLED_LIBRARY = PROJECT_ROOT / DEFAULT_LIBRARY_NAME


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


def _parse_terminal_details(details_text: str) -> list[dict]:
    details: list[dict] = []
    for line in details_text.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        detail: dict = {}
        for key, value in zip(("extension", "serial_number", "mac", "propiedad"), parts):
            if value:
                detail[key] = value.lower() if key == "propiedad" else value
        details.append(detail)
    return details


def _expand_terminal_equipment(equipos: list[dict], details: list[dict]) -> list[dict]:
    expanded: list[dict] = []
    detail_index = 0
    terminal_types = {"telefono", "terminal_dect"}
    for team in equipos:
        tipo = team.get("tipo", "pc")
        qty = max(1, int(team.get("cantidad", 1)))
        if tipo not in terminal_types:
            clean_team = {key: value for key, value in team.items() if key != "extensiones" or value}
            clean_team["cantidad"] = qty
            expanded.append(clean_team)
            continue

        extensions = team.get("extensiones") or []
        for index in range(qty):
            item = {
                "tipo": tipo,
                "modelo": team.get("modelo", ""),
                "cantidad": 1,
                "propiedad": team.get("propiedad", "propio"),
            }
            detail = details[detail_index] if detail_index < len(details) else {}
            detail_index += 1
            extension = detail.get("extension") or (extensions[index] if index < len(extensions) else "")
            if extension:
                item["extension"] = extension
            for key in ("serial_number", "mac", "propiedad"):
                if detail.get(key):
                    item[key] = detail[key]
            expanded.append(item)
    return expanded


def form_to_structured_data(form: dict) -> dict:
    legacy = _form_to_legacy_data(form)
    router = legacy.get("router", {})
    router_item = {
        "tipo": "router",
        "modelo": _clean_text(router.get("modelo")),
        "ip": _clean_text(router.get("ip")),
        "cantidad": 1,
    }
    router_item = {key: value for key, value in router_item.items() if value != ""}

    details = _parse_terminal_details(_clean_text(form.get("terminal_details")))
    equipment = _expand_terminal_equipment(legacy.get("equipos", []), details)
    equipment = [item for item in equipment if item.get("tipo") in ALLOWED_EQUIPMENT_TYPES]

    return {
        "cliente": {
            "nombre": legacy.get("cliente", ""),
            "cif": legacy.get("cif", ""),
            "direccion": legacy.get("direccion", ""),
        },
        "sedes": [
            {
                "nombre": legacy.get("sede") or "Sede Principal",
                "conectividad": {
                    key: value
                    for key, value in {
                        "tipo": legacy.get("internet", {}).get("tipo", ""),
                        "velocidad": legacy.get("internet", {}).get("velocidad", ""),
                        "capacidad": legacy.get("internet", {}).get("capacidad", ""),
                        "proveedor": legacy.get("internet", {}).get("proveedor", ""),
                        "backup": legacy.get("internet", {}).get("backup", ""),
                        "ont": legacy.get("ont", {}).get("modelo", ""),
                    }.items()
                    if value
                },
                "equipos": [router_item, *equipment],
            }
        ],
    }


def structured_to_generator_data(data: dict) -> dict:
    client = data.get("cliente", {})
    site = (data.get("sedes") or [{}])[0]
    connectivity = site.get("conectividad", {})
    equipment = list(site.get("equipos", []))
    router = next((item for item in equipment if item.get("tipo") == "router"), {})
    legacy_equipment: list[dict] = []
    for item in equipment:
        if item.get("tipo") in {"router", "ont"}:
            continue
        converted = dict(item)
        if converted.get("extension"):
            converted["extensiones"] = [converted.pop("extension")]
        legacy_equipment.append(converted)
    legacy = {
        "cliente": client.get("nombre", ""),
        "cif": client.get("cif", ""),
        "sede": site.get("nombre", "Sede Principal"),
        "direccion": client.get("direccion", ""),
        "internet": {
            "tipo": connectivity.get("tipo", ""),
            "velocidad": connectivity.get("velocidad", ""),
            "capacidad": connectivity.get("capacidad", ""),
            "proveedor": connectivity.get("proveedor", ""),
            "backup": connectivity.get("backup", ""),
        },
        "ont": {"modelo": connectivity.get("ont", "")},
        "router": {"modelo": router.get("modelo", ""), "ip": router.get("ip", "")},
        "equipos": legacy_equipment,
    }
    infer_template(legacy)
    return legacy


def sanitize_filename(cliente: str, sede: str) -> str:
    base = f"{_clean_text(cliente)}_{_clean_text(sede)}"
    normalized = re.sub(r"\s+", "_", base)
    normalized = re.sub(r"[^A-Za-z0-9._-]", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("._")
    return f"{normalized or 'drawio_output'}.drawio"


def _form_to_legacy_data(form: dict) -> dict:
    raw_text = _clean_text(form.get("raw_text"))
    data = parse_natural_text(raw_text) if raw_text else {"internet": {}, "ont": {}, "router": {}, "equipos": []}

    data["cliente"] = _clean_text(form.get("cliente")) or data.get("cliente", "")
    data["cif"] = _clean_text(form.get("cif")) or data.get("cif", "")
    data["sede"] = _clean_text(form.get("sede")) or data.get("sede", "")
    data["direccion"] = _clean_text(form.get("direccion")) or data.get("direccion", "")

    internet = data.setdefault("internet", {})
    ont = data.setdefault("ont", {})
    internet["tipo"] = _clean_text(form.get("internet_tipo")) or internet.get("tipo", "")
    internet["velocidad"] = _clean_text(form.get("internet_velocidad")) or internet.get("velocidad", "")
    internet["proveedor"] = _clean_text(form.get("internet_proveedor")) or internet.get("proveedor", "")
    if internet["tipo"] == "SOLO 4G MONITORIZADO":
        internet["capacidad"] = internet["velocidad"]
        internet["velocidad"] = ""
        internet["backup"] = ""
        ont["modelo"] = ""
    else:
        internet["capacidad"] = ""
        internet["backup"] = _clean_text(form.get("backup_modelo")) or internet.get("backup", "")
        ont["modelo"] = _clean_text(form.get("ont_modelo")) or ont.get("modelo", "")

    router = data.setdefault("router", {})
    router["modelo"] = _clean_text(form.get("router_modelo")) or router.get("modelo", "")
    router["ip"] = _clean_text(form.get("router_ip")) or router.get("ip", "")

    merged_model, merged_ip = _parse_router_ip(router.get("modelo", ""), router.get("ip", ""))
    router["modelo"] = merged_model
    router["ip"] = merged_ip
    if resolve_alias(router["modelo"]) == "CHATEAU":
        internet["backup"] = ""

    device_equipos = devices_json_to_equipos(_clean_text(form.get("devices_json")))
    legacy_equipos_text = _clean_text(form.get("equipos_text"))
    if legacy_equipos_text:
        device_equipos.extend(_parse_equipment_block(legacy_equipos_text))

    equipment_text = "\n".join(
        text
        for text in (
            _clean_text(form.get("terminal_equipment_text")),
        )
        if text
    )
    terminal_equipos = _parse_equipment_block(equipment_text) if equipment_text else []
    if device_equipos or terminal_equipos:
        data["equipos"] = [*device_equipos, *terminal_equipos]
    else:
        data.setdefault("equipos", [])

    infer_template(data)
    return data


def form_to_data(form: dict) -> dict:
    return structured_to_generator_data(form_to_structured_data(form))


def validate_web_data(data: dict) -> list[str]:
    errors = []
    for field in REQUIRED_FIELDS:
        if not _clean_text(data.get(field)):
            errors.append(f"El campo '{field}' es obligatorio.")
    return errors


def resolve_library_path(library_path: str | Path) -> Path:
    path = Path(library_path)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend(
            [
                Path.cwd() / path,
                PROJECT_ROOT / path,
                PROJECT_ROOT.parent / path,
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate
        if candidate.is_dir():
            named = candidate / DEFAULT_LIBRARY_NAME
            if named.is_file():
                return named
            for xml_file in sorted(candidate.glob("*.xml")):
                if xml_file.is_file():
                    return xml_file

    if BUNDLED_LIBRARY.is_file():
        return BUNDLED_LIBRARY
    return candidates[0] if candidates else path


def build_drawio_from_data(data: dict, library_path: str | Path) -> WebGenerationResult:
    errors = validate_web_data(data)
    if errors:
        raise ValueError("\n".join(errors))

    resolved_library = resolve_library_path(library_path)
    if not resolved_library.is_file():
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
