from __future__ import annotations

import json
import re
from pathlib import Path


REQUIRED_FIELDS = ("cliente", "sede", "direccion")


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
    match = re.match(r"(?P<qty>\d+)\s+(?P<rest>.+)", line, re.IGNORECASE)
    if not match:
        return None
    qty = int(match.group("qty"))
    rest = match.group("rest").strip()
    ext_match = re.search(r",?\s*extensi\S*nes?\s+(.+)$|,?\s*extensi\S*n\s+(.+)$", rest, re.IGNORECASE)
    extensions: list[str] = []
    if ext_match:
        ext_text = next(group for group in ext_match.groups() if group)
        extensions = re.findall(r"\d{2,6}", ext_text)
        rest = rest[: ext_match.start()].strip(" ,")

    tipo = "otro"
    lowered = rest.lower()
    if "switch" in lowered:
        tipo = "switch"
    elif (
        "telefono" in lowered
        or "fanvil" in lowered
        or "yealink" in lowered
        or "w60b" in lowered
        or "w70b" in lowered
        or "w71h" in lowered
        or "w53" in lowered
        or "w73" in lowered
        or "w80b" in lowered
        or "w90b" in lowered
    ):
        tipo = "telefono"
    elif "pc" in lowered:
        tipo = "pc"
    elif "camara" in lowered:
        tipo = "camara"
    elif "wifi" in lowered or "ap " in lowered:
        tipo = "wifi"
    elif "ata" in lowered:
        tipo = "ata"

    model = rest.strip(" ,")
    return {"tipo": tipo, "modelo": model, "cantidad": qty, "extensiones": extensions}


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
