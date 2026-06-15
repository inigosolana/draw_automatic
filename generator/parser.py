from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


REQUIRED_FIELDS = ("cliente", "sede", "direccion")


@dataclass(frozen=True)
class ValidatedEquipment:
    cantidad: int
    extensiones: list[str]

    @classmethod
    def from_dict(cls, team: dict, index: int) -> ValidatedEquipment:
        label = str(team.get("modelo") or team.get("tipo") or f"equipo {index + 1}")
        quantity = team.get("cantidad", 1)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError(
                f"El campo 'cantidad' del equipo '{label}' debe ser un entero positivo."
            )
        extensions = team.get("extensiones", [])
        if extensions is None:
            extensions = []
        if not isinstance(extensions, list) or any(not isinstance(value, str) for value in extensions):
            raise ValueError(
                f"El campo 'extensiones' del equipo '{label}' debe ser una lista de textos."
            )
        return cls(cantidad=quantity, extensiones=extensions)


def validate_input_schema(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("La entrada debe ser un objeto JSON.")
    equipment = data.get("equipos", [])
    if equipment is None:
        data["equipos"] = []
        return
    if not isinstance(equipment, list):
        raise ValueError("El campo 'equipos' debe ser una lista.")
    for index, team in enumerate(equipment):
        if not isinstance(team, dict):
            raise ValueError(f"El equipo en la posicion {index + 1} debe ser un objeto.")
        ValidatedEquipment.from_dict(team, index)


def load_input(path: str | Path) -> dict:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = parse_natural_text(text)
    missing = [field for field in REQUIRED_FIELDS if not data.get(field)]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Faltan campos obligatorios: {joined}")
    data.setdefault("equipos", [])
    validate_input_schema(data)
    infer_template(data)
    return data


def parse_natural_text(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    data: dict = {
        "internet": {},
        "ont": {},
        "router": {},
        "equipos": [],
    }
    in_equipment = False
    for line in lines:
        lower = line.lower()
        if lower.startswith("cliente:"):
            data["cliente"] = line.split(":", 1)[1].strip()
        elif lower.startswith("cif:"):
            data["cif"] = line.split(":", 1)[1].strip()
        elif lower.startswith("sede:"):
            data["sede"] = line.split(":", 1)[1].strip()
        elif lower.startswith("dirección:") or lower.startswith("direccion:"):
            data["direccion"] = line.split(":", 1)[1].strip()
        elif lower.startswith("internet:"):
            payload = line.split(":", 1)[1].strip()
            speed = re.search(r"(\d+\s*(?:gb|mb))", payload, re.IGNORECASE)
            kind = payload.replace(speed.group(0), "").strip() if speed else payload
            data["internet"] = {"tipo": kind, "velocidad": speed.group(1) if speed else ""}
        elif lower.startswith("ont:"):
            data["ont"]["modelo"] = line.split(":", 1)[1].strip()
        elif lower.startswith("router:"):
            payload = line.split(":", 1)[1].strip()
            ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})", payload)
            if ip_match:
                data["router"]["ip"] = ip_match.group(1)
                payload = payload.replace(ip_match.group(1), "").replace("-", " ").strip()
            data["router"]["modelo"] = payload.strip(" -")
        elif lower.startswith("equipos"):
            in_equipment = True
        elif in_equipment and (line.startswith("*") or line.startswith("-")):
            equipment = parse_equipment_line(line[1:].strip())
            if equipment:
                data["equipos"].append(equipment)
    return data


def parse_equipment_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    match = re.match(r"(?P<qty>\d+)\s+(?P<rest>.+)", line, re.IGNORECASE)
    qty = int(match.group("qty")) if match else 1
    rest = match.group("rest").strip() if match else line
    if qty <= 0:
        raise ValueError(f"El campo 'cantidad' del equipo '{rest}' debe ser un entero positivo.")
    ownership = "ajeno" if re.search(r"\b(ajeno|no nuestro)\b", rest, re.IGNORECASE) else "propio"
    rest = re.sub(r"\s*[\[(]?\b(?:propio|nuestro|ajeno|no nuestro)\b[\])]?\s*", " ", rest, flags=re.IGNORECASE).strip()
    ext_match = re.search(r",?\s*extensi\S*nes?\s+(.+)$|,?\s*extensi\S*n\s+(.+)$", rest, re.IGNORECASE)
    extensions: list[str] = []
    if ext_match:
        ext_text = next(group for group in ext_match.groups() if group)
        extensions = re.findall(r"\d{2,6}", ext_text)
        rest = rest[: ext_match.start()].strip(" ,")

    tipo = "pc"
    lowered = rest.lower()
    if "switch" in lowered:
        tipo = "switch"
    elif any(model in lowered for model in ("w60b", "w70b", "w80b", "w90b")):
        tipo = "base_dect"
    elif any(model in lowered for model in ("w71h", "w53", "w53h", "w73", "w73h")):
        tipo = "terminal_dect"
    elif "ont" in lowered:
        tipo = "ont"
    elif "router" in lowered or "chateau" in lowered or "mikrotik" in lowered:
        tipo = "router"
    elif "ata" in lowered:
        tipo = "ata"
    elif (
        "telefono" in lowered
        or "fanvil" in lowered
        or "yealink" in lowered
        or "grandstream" in lowered
        or "gxp" in lowered
        or any(
            token in lowered
            for token in (
                "t-27",
                "t27",
                "t-30",
                "t30",
                "t-31",
                "t31",
                "t-33",
                "t33",
                "t-43",
                "t43",
                "t-44",
                "t44",
                "t-73",
                "t73",
            )
        )
    ):
        tipo = "telefono"
    elif "pc" in lowered:
        tipo = "pc"

    model = rest.strip(" ,")
    return {
        "tipo": tipo,
        "modelo": model,
        "cantidad": qty,
        "extensiones": extensions,
        "propiedad": ownership,
    }


def infer_template(data: dict) -> None:
    if data.get("template"):
        return
    equipment = data.get("equipos", [])
    switch_count = sum(1 for item in equipment if item.get("tipo") == "switch")
    if isinstance(data.get("sedes"), list) and len(data["sedes"]) > 1:
        data["template"] = "multisede"
    elif switch_count > 1 or any(item.get("tipo") in {"patch_panel", "firewall", "sai"} for item in equipment):
        data["template"] = "rack"
    elif switch_count == 1:
        data["template"] = "con_switch"
    else:
        data["template"] = "oficina_simple"
