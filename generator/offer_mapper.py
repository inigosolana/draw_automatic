from __future__ import annotations

import re
from dataclasses import dataclass, field


ACCESSORY_PATTERN = re.compile(
    r"\b("
    r"cargador|psu|power\s*supply|fuente(?:\s+de\s+alimentaci[oó]n)?|"
    r"alimentaci[oó]n|adaptador(?:\s+de\s+corriente)?|cable|patch\s*cord|"
    r"soporte|mount|bracket|clip|tornillo|kit\s*de\s*montaje|bater[ií]a\s*de\s*respaldo"
    r")\b",
    re.IGNORECASE,
)

DECT_BASE_PATTERN = re.compile(r"\b(w60b|w70b|w80b|w90dm|yealink\s*w90dm)\b", re.IGNORECASE)
DECT_HANDSET_PATTERN = re.compile(r"\b(w71h|w72h|w53h|w73h)\b", re.IGNORECASE)
SIP_TERMINAL_PATTERN = re.compile(r"\b(?:sip[-\s]?t(\d{2})g?|t[-\s]?(\d{2}))\b", re.IGNORECASE)
FANVIL_PATTERN = re.compile(r"\bfanvil\s*(v\d{2})?\b", re.IGNORECASE)

FIBER_PROVIDERS = {
    "movistar(aire)": "AIRE",
    "movistar aire": "AIRE",
    "aire": "AIRE",
    "adamo": "ADAMO",
    "mas movil": "MAS MOVIL",
    "masmovil": "MAS MOVIL",
    "euskaltel": "EUSKALTEL",
    "sarenet orange": "SARENET ORANGE",
    "sarenet": "SARENET",
}

SPEED_PATTERN = re.compile(r"\b(300\s*mb|600\s*mb|1\s*gb)\b", re.IGNORECASE)


@dataclass
class OfferProduct:
    name: str
    quantity: int = 1


@dataclass
class ImportResult:
    work_order_id: str = ""
    cliente: str = ""
    cif: str = ""
    sede: str = ""
    direccion: str = ""
    internet_tipo: str = ""
    internet_proveedor: str = ""
    internet_velocidad: str = ""
    ont_modelo: str = ""
    router_modelo: str = ""
    backup_modelo: str = ""
    router_ip: str = ""
    devices_json: list[dict] = field(default_factory=list)
    terminals: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def extract_work_order_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        return text
    match = re.search(r"/work-order/(\d+)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d{3,})\b", text)
    return match.group(1) if match else ""


def is_accessory(name: str) -> bool:
    return bool(ACCESSORY_PATTERN.search(name or ""))


def normalize_products(raw_products: list[object]) -> list[OfferProduct]:
    products: list[OfferProduct] = []
    for item in raw_products:
        if isinstance(item, str):
            name = item.strip()
            quantity = 1
            if not name:
                continue
            qty_match = re.match(r"^(\d+)\s*[x×]\s*(.+)$", name, re.IGNORECASE)
            if qty_match:
                quantity = max(1, int(qty_match.group(1)))
                name = qty_match.group(2).strip()
            products.append(OfferProduct(name=name, quantity=quantity))
            continue
        if not isinstance(item, dict):
            continue
        name = str(
            item.get("name")
            or item.get("product")
            or item.get("description")
            or item.get("title")
            or item.get("model")
            or ""
        ).strip()
        if not name:
            continue
        quantity = item.get("quantity") or item.get("qty") or item.get("amount") or 1
        try:
            quantity = max(1, int(quantity))
        except (TypeError, ValueError):
            quantity = 1
        products.append(OfferProduct(name=name, quantity=quantity))
    return products


def parse_product_lines(text: str) -> list[OfferProduct]:
    lines = [line.strip(" -*•\t") for line in text.splitlines()]
    return normalize_products([line for line in lines if line])


def _normalize_dect_base(name: str) -> str:
    match = DECT_BASE_PATTERN.search(name)
    if not match:
        return ""
    token = match.group(1).upper().replace("YEALINK ", "")
    if token == "W90DM":
        return "YEALINK W90DM"
    return token


def _normalize_terminal_model(name: str) -> str:
    handset = DECT_HANDSET_PATTERN.search(name)
    if handset:
        return handset.group(1).upper()
    sip = SIP_TERMINAL_PATTERN.search(name)
    if sip:
        digits = sip.group(1) or sip.group(2)
        return f"T-{digits}"
    fanvil = FANVIL_PATTERN.search(name)
    if fanvil:
        version = fanvil.group(1)
        return f"FANVIL V{version[1:]}" if version else "FANVIL V62"
    lowered = name.lower()
    for token in ("t-33", "t-31", "t-30", "t-43", "t-44", "t-73"):
        if token.replace("-", "") in lowered.replace("-", "").replace(" ", ""):
            return token.upper()
    return ""


def _detect_router_model(name: str) -> str:
    lowered = name.lower()
    if "chateau" in lowered or "s53ug" in lowered or "ax r17" in lowered:
        return "CHATEAU"
    if "hap ac3" in lowered or "ac3" in lowered and "hap" in lowered:
        return "MikroTik hAP ac3"
    if "hap ac2" in lowered or ("ac2" in lowered and "hap" in lowered):
        return "MikroTik hAP ac2"
    if "mikrotik" in lowered:
        return "MikroTik hAP ac2"
    return ""


def _detect_ont_model(name: str, provider: str) -> str:
    lowered = name.lower()
    if "ont" not in lowered and "gpon" not in lowered:
        return ""
    if "adamo" in lowered or provider == "ADAMO":
        return "ONT ADAMO"
    return "ONT ZTE"


def _detect_backup_model(name: str) -> str:
    lowered = name.lower()
    if "teltonika" in lowered:
        return "TELTONIKA"
    if "wap lte" in lowered or re.search(r"\bwap\b", lowered):
        return "WAP LTE"
    return ""


def _detect_device_category(name: str) -> tuple[str, str, str] | None:
    lowered = name.lower()
    if any(token in lowered for token in ("switch", "swtich", "tp-link", "tp link", "dgs", "firebox")):
        model = name.strip()
        if "switch" not in model.lower():
            model = f"switch {model}"
        return ("switch", "switch", model)
    if any(token in lowered for token in ("deco", "mesh", "access point", "punto de acceso", " gwn", " ruijie", " wifi")):
        return ("ap", "wifi", name.strip())
    if "ata" in lowered:
        return ("ata", "ata", "ATA")
    if "nas" in lowered:
        return ("nas", "otro", "nas")
    return None


def _normalize_provider(text: str) -> str:
    lowered = (text or "").lower()
    for key, value in sorted(FIBER_PROVIDERS.items(), key=lambda item: len(item[0]), reverse=True):
        if key in lowered:
            return value
    return ""


def _normalize_speed(text: str) -> str:
    match = SPEED_PATTERN.search(text or "")
    if not match:
        return ""
    token = match.group(1).upper().replace(" ", " ")
    if token.startswith("1"):
        return "1 GB"
    if token.startswith("600"):
        return "600 MB"
    if token.startswith("300"):
        return "300 MB"
    return ""


def _infer_internet_type(text: str, has_backup_device: bool) -> str:
    lowered = (text or "").lower()
    if "4g monitorizado" in lowered or "solo 4g" in lowered:
        return "SOLO 4G MONITORIZADO"
    if has_backup_device or re.search(r"fibra\s*\+\s*bu\b", lowered) or "fibra + back" in lowered or "fibra + backup" in lowered or re.search(r"\bbackup\b", lowered):
        return "FIBRA + BACK UP"
    if "fibra" in lowered or "ftth" in lowered or "gpon" in lowered:
        return "SOLO FIBRA"
    return ""


def map_offer_to_form(
    products: list[OfferProduct],
    *,
    cliente: str = "",
    cif: str = "",
    sede: str = "",
    direccion: str = "",
    connectivity_text: str = "",
    work_order_id: str = "",
) -> ImportResult:
    result = ImportResult(
        work_order_id=work_order_id,
        cliente=cliente.strip(),
        cif=cif.strip(),
        sede=sede.strip(),
        direccion=direccion.strip(),
    )
    dect_bases: list[str] = []
    pending_devices: list[dict] = []
    connectivity_blob = connectivity_text or ""
    active_products: list[OfferProduct] = []

    for product in products:
        name = product.name.strip()
        if not name:
            continue
        if is_accessory(name):
            result.warnings.append(f"Accesorio ignorado: {name}")
            continue
        active_products.append(product)

    for product in active_products:
        name = product.name.strip()
        dect_base = _normalize_dect_base(name)
        if dect_base and (
            re.search(r"\bbase\b", name, re.IGNORECASE) or not _normalize_terminal_model(name)
        ):
            for _ in range(max(1, product.quantity)):
                dect_bases.append(dect_base)

    for product in active_products:
        name = product.name.strip()
        quantity = max(1, product.quantity)
        connectivity_blob = f"{connectivity_blob} {name}"

        dect_base = _normalize_dect_base(name)
        if dect_base and (
            re.search(r"\bbase\b", name, re.IGNORECASE) or not _normalize_terminal_model(name)
        ):
            continue

        terminal_model = _normalize_terminal_model(name)
        if terminal_model:
            is_dect_handset = terminal_model in {"W71H", "W72H", "W53H", "W73H"}
            for _ in range(quantity):
                assigned_base = ""
                if is_dect_handset:
                    assigned_base = dect_bases.pop(0) if dect_bases else ""
                    if not assigned_base:
                        assigned_base = {
                            "W71H": "W60B",
                            "W72H": "W60B",
                            "W53H": "W60B",
                            "W73H": "W60B",
                        }.get(terminal_model, "W60B")
                result.terminals.append(
                    {
                        "model": terminal_model,
                        "dect_base": assigned_base,
                        "extension": "",
                        "serial": "",
                        "mac": "",
                        "ip": "",
                        "ownership": "propio",
                    }
                )
            continue

        router_model = _detect_router_model(name)
        if router_model and not result.router_modelo:
            result.router_modelo = router_model
            continue

        ont_model = _detect_ont_model(name, result.internet_proveedor)
        if ont_model and not result.ont_modelo:
            result.ont_modelo = ont_model
            continue

        backup_model = _detect_backup_model(name)
        if backup_model and not result.backup_modelo:
            result.backup_modelo = backup_model
            continue

        device = _detect_device_category(name)
        if device:
            category_id, tipo, modelo = device
            pending_devices.append(
                {
                    "category": category_id,
                    "tipo": tipo,
                    "modelo": modelo,
                    "cantidad": quantity,
                    "propiedad": "propio",
                }
            )
            continue

        if "router" in name.lower() or "ont" in name.lower():
            result.warnings.append(f"Producto de conectividad no mapeado automaticamente: {name}")
        else:
            result.warnings.append(f"Producto no clasificado (revisar manualmente): {name}")

    result.devices_json = pending_devices

    provider = _normalize_provider(connectivity_blob)
    if provider:
        result.internet_proveedor = provider

    speed = _normalize_speed(connectivity_blob)
    if speed:
        result.internet_velocidad = speed

    internet_type = _infer_internet_type(connectivity_blob, bool(result.backup_modelo))
    if internet_type:
        result.internet_tipo = internet_type
    elif result.ont_modelo or result.router_modelo:
        result.internet_tipo = "SOLO FIBRA"

    if result.internet_tipo == "FIBRA + BACK UP" and result.router_modelo == "CHATEAU":
        result.backup_modelo = ""

    if not result.sede:
        result.sede = "Sede Principal"

    return result
