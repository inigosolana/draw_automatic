"""Adaptador entre el formulario web y el motor de dibujado.

Conviven DOS formatos de datos a propósito:

- **structured** (`form_to_structured_data`): refleja el formulario tal cual, con
  bloques separados por equipo (terminales, dispositivos, internet…). Es el que
  consume el frontend y el preview JSON.
- **legacy / generator** (`structured_to_generator_data`): la forma plana que
  espera `layout_engine.build_layout` (`data["equipos"]`, `data["router"]`, …).

`form_to_data` hace structured → generator porque el motor de layout solo
entiende el formato legacy, mientras que el resto de la app (preview, edición,
importación de OT) trabaja con el structured. Mantener ambos evita reescribir el
motor de layout; el coste es esta conversión explícita en un único sitio.

Flujo canónico (una sola dirección, NO hay round-trip de vuelta):

    form (dict del POST)
      │  form_to_structured_data()
      ▼
    structured  ──────────────► preview JSON / edición / OT
      │  structured_to_generator_data()
      ▼
    legacy/generator  ────────► layout_engine.build_layout()

`form_to_data(form)` es exactamente `structured_to_generator_data(form_to_
structured_data(form))`; no existe ni hace falta `generator_to_structured`.
Por eso, aunque haya dos formatos, el dato fluye en un solo sentido y no se
"ida y vuelta": cada paso es una proyección que pierde detalle (p. ej. legacy
colapsa terminales por extensión), y reconstruir hacia atrás no es un objetivo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .aliases import resolve_alias
from .device_catalog import devices_json_to_equipos
from .drawio_writer import BuildResult, build_drawio
from .layout_engine import build_layout, validate_input_data
from .layout_types import EdgeSpec, NodeSpec
from .library_loader import load_library, validate_library_file
from .layout_engine import _parse_switch_telefonia
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
BUNDLED_LIBRARY = PROJECT_ROOT / "library" / DEFAULT_LIBRARY_NAME


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


def _terminal_detail_keys(parts: list[str]) -> tuple[str, ...]:
    has_model = bool(
        parts
        and parts[0]
        and not parts[0].isdigit()
        and any(char.isalpha() for char in parts[0])
    )
    if has_model:
        if len(parts) >= 7:
            return ("model", "extension", "serial_number", "mac", "ip", "propiedad", "dect_base")
        return ("model", "extension", "serial_number", "mac", "propiedad", "dect_base")
    if len(parts) >= 6 and (parts[3] or "").lower() in {"propio", "ajeno"}:
        return ("extension", "serial_number", "mac", "propiedad", "dect_base", "model")
    return ("extension", "serial_number", "mac", "ip", "propiedad", "dect_base", "model")


def _parse_terminal_details(details_text: str) -> list[dict]:
    details: list[dict] = []
    for line in details_text.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        detail: dict = {}
        keys = _terminal_detail_keys(parts)
        for key, value in zip(keys, parts):
            if not value:
                continue
            if key == "propiedad":
                detail[key] = value.lower()
            else:
                detail[key] = value
        details.append(detail)
    return details


def _as_qty(value: object) -> int:
    """Cantidad tolerante: None / texto no numérico → 1 (mínimo 1)."""
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _expand_terminal_equipment(equipos: list[dict], details: list[dict]) -> list[dict]:
    expanded: list[dict] = []
    detail_index = 0
    terminal_types = {"telefono", "terminal_dect"}
    for team in equipos:
        tipo = team.get("tipo", "pc")
        qty = _as_qty(team.get("cantidad", 1))
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
            for key in ("serial_number", "mac", "ip", "propiedad", "dect_base"):
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
                "switch_telefonia": legacy.get("switch_telefonia", True),
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
        "switch_telefonia": site.get("switch_telefonia", True),
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
    data["switch_telefonia"] = _parse_switch_telefonia(form.get("switch_telefonia"), default=True)

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
    if internet["tipo"] == "SOLO 4G MONITORIZADO":
        router["modelo"] = "CHATEAU"
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
                PROJECT_ROOT / "library" / path.name,
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


def build_drawio_from_box_editor(payload: dict, library_path: str | Path) -> BuildResult:
    """Construye el XML draw.io desde el estado EDITADO del editor de cajas.

    payload = {"boxes": [{"id","type","model","label","x","y","w","h"}],
               "links": [{"a","b"}]}.
    Cada caja conserva su posición; el icono se resuelve por su `model` (las cajas
    de internet se dibujan como nube; las que no tienen model, como texto).
    Se usa solo cuando el técnico ha editado la vista previa antes de generar.
    """
    resolved_library = resolve_library_path(library_path)
    if not resolved_library.is_file():
        raise FileNotFoundError("No se ha encontrado la libreria. Revisa la ruta.")
    library = load_library(resolved_library)

    boxes = payload.get("boxes") if isinstance(payload, dict) else None
    if not isinstance(boxes, list) or not boxes:
        raise ValueError("El editor de cajas no tiene contenido.")
    boxes = boxes[:200]  # tope defensivo

    nodes: list[NodeSpec] = []
    valid_ids: set[str] = set()
    for box in boxes:
        if not isinstance(box, dict):
            continue
        box_id = str(box.get("id") or "").strip()
        if not box_id or box_id in valid_ids:
            continue
        label = _clean_text(box.get("label"))
        box_type = str(box.get("type") or "").strip()
        model = _clean_text(box.get("model"))

        def _int(value, default):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return default

        x = max(0, min(_int(box.get("x"), 0), 5000))
        y = max(0, min(_int(box.get("y"), 0), 5000))
        width = max(40, min(_int(box.get("w"), 120), 400))
        height = max(30, min(_int(box.get("h"), 80), 400))

        if box_type == "internet":
            kind, model = "cloud", None
        elif model:
            kind = "device"
        else:
            kind = "text"
        nodes.append(
            NodeSpec(key=box_id, kind=kind, label=label, x=x, y=y, width=width, height=height, model=model)
        )
        valid_ids.add(box_id)

    if not nodes:
        raise ValueError("El editor de cajas no tiene cajas válidas.")

    edges: list[EdgeSpec] = []
    for link in payload.get("links") or []:
        if not isinstance(link, dict):
            continue
        a, b = str(link.get("a") or ""), str(link.get("b") or "")
        if a in valid_ids and b in valid_ids and a != b:
            edges.append(EdgeSpec(source=a, target=b))

    return build_drawio(nodes, edges, library)


def build_drawio_from_data(data: dict, library_path: str | Path) -> WebGenerationResult:
    errors = validate_web_data(data)
    if errors:
        raise ValueError("\n".join(errors))

    resolved_library = resolve_library_path(library_path)
    if not resolved_library.is_file():
        raise FileNotFoundError("No se ha encontrado la libreria. Revisa la ruta.")

    library = load_library(resolved_library)
    warnings = validate_input_data(data)
    warnings.extend(validate_library_file(resolved_library))
    nodes, edges = build_layout(data)
    result = build_drawio(nodes, edges, library, warnings=warnings)
    total_equipment = sum(_as_qty(team.get("cantidad", 1)) for team in data.get("equipos", []))
    return WebGenerationResult(
        result=result,
        data=data,
        filename=sanitize_filename(data.get("cliente", ""), data.get("sede", "")),
        total_equipment=total_equipment,
    )
