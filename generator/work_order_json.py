from __future__ import annotations

import re

from .import_errors import CommsError
from .address_formatter import normalize_street_address
from .equipment_detection import (
    _detect_backup_model,
    _detect_ont_model,
    _detect_router_model,
    _normalize_dect_base,
    _normalize_provider,
    _normalize_speed,
    _normalize_terminal_model,
)
from .offer_mapper import (
    ImportResult,
    _infer_internet_type,
    extract_work_order_id,
    is_accessory,
    is_headset,
    map_offer_to_form,
    normalize_products,
)


INTERNET_TYPE_ALIASES = {
    "fibra + back up": "FIBRA + BACK UP",
    "fibra + backup": "FIBRA + BACK UP",
    "fibra + bu": "FIBRA + BACK UP",
    "fibra y backup": "FIBRA + BACK UP",
    "solo fibra": "SOLO FIBRA",
    "ftth": "SOLO FIBRA",
    "solo 4g monitorizado": "SOLO 4G MONITORIZADO",
    "4g monitorizado": "SOLO 4G MONITORIZADO",
}

PROVIDER_ALIASES = {
    "aire": "AIRE",
    "movistar": "AIRE",
    "movistar aire": "AIRE",
    "mas movil": "MAS MOVIL",
    "masmovil": "MAS MOVIL",
    "más móvil": "MAS MOVIL",
    "adamo": "ADAMO",
    "euskaltel": "EUSKALTEL",
    "sarenet orange": "SARENET ORANGE",
    "sarenet": "SARENET",
}

DECT_HANDSET_MODELS = frozenset({"W71H", "W72H", "W53H", "W73H"})


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _normalize_internet_type(value: str) -> str:
    lowered = _clean(value).lower()
    if not lowered:
        return ""
    if lowered in INTERNET_TYPE_ALIASES:
        return INTERNET_TYPE_ALIASES[lowered]
    upper = _clean(value).upper()
    if upper in {"FIBRA + BACK UP", "SOLO FIBRA", "SOLO 4G MONITORIZADO"}:
        return upper
    return ""


def _normalize_provider_value(value: str) -> str:
    cleaned = _clean(value)
    if not cleaned:
        return ""
    alias = PROVIDER_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    normalized = _normalize_provider(cleaned)
    if normalized:
        return normalized
    upper = cleaned.upper()
    if upper in PROVIDER_ALIASES.values():
        return upper
    return cleaned.upper()


def _normalize_crm_mac(mac: str) -> str:
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(cleaned) == 12:
        return ":".join(cleaned[index : index + 2] for index in range(0, 12, 2)).upper()
    return _clean(mac)


def _strip_vendor_prefix(product_name: str) -> str:
    name = _clean(product_name)
    if " - " in name:
        return name.split(" - ", 1)[1].strip()
    return name


def _crm_equipment_field(item: dict, *keys: str) -> str:
    for key in keys:
        if key not in item:
            continue
        value = item.get(key)
        if value is None:
            continue
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return ""


def _iter_crm_equipment_items(equipments: object) -> list[dict]:
    if isinstance(equipments, dict):
        return [item for item in equipments.values() if isinstance(item, dict)]
    if isinstance(equipments, list):
        return [item for item in equipments if isinstance(item, dict)]
    return []


def _collect_crm_dect_bases(items: list[dict]) -> list[str]:
    bases: list[str] = []
    for item in items:
        product_name = _crm_equipment_field(item, "productName", "product_name", "name", "model")
        if not product_name:
            continue
        clean_name = _strip_vendor_prefix(product_name)
        dect_base = _normalize_dect_base(clean_name)
        if dect_base and re.search(r"\bbase\b", clean_name, re.IGNORECASE):
            if dect_base not in bases:
                bases.append(dect_base)
    return bases


def _assign_dect_bases_to_handsets(
    terminals: list[dict],
    dect_bases: list[str],
    handset_bases_from_order: list[str],
) -> None:
    """Una base DECT puede alimentar varios terminales inalambricos (W71H, W53H...)."""
    single_base = dect_bases[0] if len(dect_bases) == 1 else ""
    handset_index = 0
    for terminal in terminals:
        if terminal.get("model") not in DECT_HANDSET_MODELS:
            continue
        if single_base:
            terminal["dect_base"] = single_base
        elif handset_index < len(handset_bases_from_order):
            ordered_base = handset_bases_from_order[handset_index]
            if ordered_base:
                terminal["dect_base"] = ordered_base
        handset_index += 1


def _parse_crm_equipments(equipments: object) -> dict:
    items = _iter_crm_equipment_items(equipments)
    products: list[dict] = []
    terminals: list[dict] = []
    connectivity_parts: list[str] = []
    active_dect_base = ""
    handset_bases_from_order: list[str] = []
    dect_bases_found = _collect_crm_dect_bases(items)

    for item in items:
        product_name = _crm_equipment_field(item, "productName", "product_name", "name", "model")
        if not product_name:
            continue
        clean_name = _strip_vendor_prefix(product_name)
        if is_headset(clean_name) or is_headset(product_name):
            continue
        if is_accessory(clean_name):
            continue
        service_name = _crm_equipment_field(item, "service_name", "serviceName")
        extension = _crm_equipment_field(item, "service_ext", "serviceExt", "extension", "ext")
        serial = _crm_equipment_field(item, "S/N", "serial_number", "serial", "sn")
        mac = _normalize_crm_mac(_crm_equipment_field(item, "MAC", "mac", "mac_address"))

        if service_name:
            connectivity_parts.append(service_name)

        dect_base = _normalize_dect_base(clean_name)
        if dect_base and re.search(r"\bbase\b", clean_name, re.IGNORECASE):
            active_dect_base = dect_base
            products.append({"name": clean_name, "quantity": 1})
            continue

        terminal_model = _normalize_terminal_model(clean_name)
        if terminal_model:
            if terminal_model in DECT_HANDSET_MODELS:
                handset_bases_from_order.append(active_dect_base)
            terminals.append(
                {
                    "model": terminal_model,
                    "extension": extension,
                    "serial": serial,
                    "mac": mac,
                    "dect_base": "",
                    "ownership": "propio",
                }
            )
            continue

        products.append({"name": clean_name, "quantity": 1})

    _assign_dect_bases_to_handsets(terminals, dect_bases_found, handset_bases_from_order)

    connectivity_text = " ".join(dict.fromkeys(connectivity_parts))
    return {
        "products": products,
        "terminals": terminals,
        "connectivity_text": connectivity_text,
        "dect_bases": dect_bases_found,
    }


def _validate_crm_terminal_fields(terminal: dict, label: str) -> None:
    if not terminal.get("serial"):
        raise CommsError(
            f"El terminal «{label}» no incluye numero de serie. "
            "El CRM debe enviar serial_number, serial, sn o S/N."
        )
    model = _clean(terminal.get("model"))
    if model not in DECT_HANDSET_MODELS and not terminal.get("mac"):
        raise CommsError(
            f"El terminal «{label}» no incluye MAC. El CRM debe enviar mac, mac_address o MAC."
        )


def unwrap_work_order_api_response(payload: object) -> dict:
    """Extract the work-order body from CRM envelopes such as ``{status, result}``."""
    if not isinstance(payload, dict):
        raise CommsError("La respuesta JSON no es un objeto valido.")

    work_order_keys = (
        "customer",
        "cliente",
        "client",
        "equipments",
        "equipment",
        "products",
        "terminals",
        "sede",
        "site",
        "location",
    )
    if any(key in payload for key in work_order_keys):
        return payload

    for wrapper_key in ("result", "data", "payload", "body"):
        inner = payload.get(wrapper_key)
        if isinstance(inner, dict):
            return inner

    return payload


def _extract_connectivity(connectivity: object, base_text: str) -> tuple[str, dict[str, str]]:
    """De un bloque de conectividad (dict estructurado o texto) saca el texto
    libre y, si es dict, los campos estructurados con sus alias."""
    connectivity_text = base_text
    connectivity_structured: dict[str, str] = {}
    if isinstance(connectivity, dict):
        connectivity_text = connectivity_text or " ".join(
            str(value) for value in connectivity.values() if value
        )
        connectivity_structured = {
            "type": _clean(connectivity.get("type") or connectivity.get("tipo")),
            "provider": _clean(
                connectivity.get("provider") or connectivity.get("proveedor") or connectivity.get("carrier")
            ),
            "speed": _clean(connectivity.get("speed") or connectivity.get("velocidad")),
            "ont_model": _clean(connectivity.get("ont_model") or connectivity.get("ont_modelo") or connectivity.get("ont")),
            "router_model": _clean(
                connectivity.get("router_model") or connectivity.get("router_modelo") or connectivity.get("router")
            ),
            "router_ip": _clean(connectivity.get("router_ip") or connectivity.get("ip")),
            "backup_model": _clean(
                connectivity.get("backup_model") or connectivity.get("backup_modelo") or connectivity.get("backup")
            ),
        }
    elif isinstance(connectivity, str):
        connectivity_text = connectivity_text or connectivity
    return connectivity_text, connectivity_structured


def _resolve_site_fields(payload: dict, site: dict, sede_raw: object) -> tuple[str, str]:
    """Resuelve (nombre de sede, dirección) combinando el dict de sede, la
    dirección de nivel superior y el caso en que `sede` venga como string."""
    top_direccion = _clean(payload.get("direccion") or payload.get("address"))
    sede_name = _clean(site.get("name") or site.get("nombre"))
    # CRM may send address_id, contact_id, matriz, contact, etc.; only name + address are used.
    sede_address = _clean(site.get("address") or site.get("direccion")) or top_direccion
    if isinstance(sede_raw, str):
        sede_text = _clean(sede_raw)
        if top_direccion:
            sede_name = sede_text
            sede_address = top_direccion
        elif not sede_name:
            sede_address = sede_text or sede_address
    return sede_name, sede_address


def normalize_work_order_payload(payload: object) -> dict:
    payload = unwrap_work_order_api_response(payload)
    if not isinstance(payload, dict):
        raise CommsError("La respuesta JSON no es un objeto valido.")

    customer = payload.get("customer") or payload.get("cliente") or payload.get("client") or {}
    site = payload.get("site") or payload.get("location") or {}
    sede_raw = payload.get("sede")
    if isinstance(sede_raw, dict):
        site = sede_raw
    if not isinstance(customer, dict):
        customer = {}
    if not isinstance(site, dict):
        site = {}

    equipments = payload.get("equipments") or payload.get("equipment")
    crm_equipment_data = _parse_crm_equipments(equipments) if equipments else None

    products = (
        (crm_equipment_data or {}).get("products")
        or payload.get("products")
        or payload.get("items")
        or payload.get("lines")
        or payload.get("equipment")
        or []
    )
    if isinstance(products, dict):
        products = products.get("items") or products.get("data") or []

    connectivity = payload.get("connectivity") or payload.get("internet") or {}
    connectivity_text, connectivity_structured = _extract_connectivity(
        connectivity, (crm_equipment_data or {}).get("connectivity_text", "")
    )

    terminals_raw = (
        (crm_equipment_data or {}).get("terminals")
        or payload.get("terminals")
        or payload.get("phones")
        or payload.get("telefonos")
        or []
    )
    if not isinstance(terminals_raw, list):
        terminals_raw = []

    sede_name, sede_address = _resolve_site_fields(payload, site, sede_raw)

    return {
        "work_order_id": _clean(payload.get("work_order_id") or payload.get("id") or payload.get("reference")),
        "cliente": _clean(
            customer.get("fullname")
            or customer.get("name")
            or customer.get("nombre")
            or payload.get("cliente")
        ),
        "cif": _clean(
            customer.get("document")
            or customer.get("tax_id")
            or customer.get("cif")
            or customer.get("nif")
            or payload.get("cif")
        ),
        "sede": sede_name or _clean(payload.get("sede") if isinstance(payload.get("sede"), str) else ""),
        "direccion": normalize_street_address(sede_address),
        "glpi_entity_id": _clean(site.get("glpi_entity_id") or site.get("entity_id") or payload.get("glpi_entity_id")),
        "connectivity_text": connectivity_text or _clean(payload.get("connectivity_text")),
        "connectivity_structured": connectivity_structured,
        "products": products if isinstance(products, list) else [],
        "terminals": terminals_raw,
        "from_crm_equipments": bool(crm_equipment_data),
        "dect_bases": (crm_equipment_data or {}).get("dect_bases") or [],
    }


def terminal_from_json_item(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    raw_model = _strip_vendor_prefix(
        _clean(
            item.get("model")
            or item.get("modelo")
            or item.get("name")
            or item.get("product")
            or item.get("productName")
            or item.get("product_name")
        )
    )
    model = _normalize_terminal_model(raw_model) or raw_model
    if not model:
        return None
    ownership = _clean(item.get("ownership") or item.get("propiedad") or "propio").lower()
    if ownership not in {"propio", "ajeno"}:
        ownership = "propio"
    dect_base = _normalize_dect_base(_clean(item.get("dect_base") or item.get("base_dect")))
    terminal = {
        "model": model,
        "extension": _clean(
            item.get("extension") or item.get("extension_sip") or item.get("ext") or item.get("service_ext")
        ),
        "serial": _clean(
            item.get("serial_number") or item.get("serial") or item.get("sn") or item.get("S/N")
        ),
        "mac": _normalize_crm_mac(_clean(item.get("mac") or item.get("mac_address") or item.get("MAC"))),
        "ip": _clean(item.get("ip")),
        "ownership": ownership,
        "dect_base": dect_base,
    }
    return terminal


def parse_terminals_from_payload(items: list[object], *, require_crm_fields: bool = False) -> list[dict]:
    terminals: list[dict] = []
    for index, item in enumerate(items, start=1):
        terminal = terminal_from_json_item(item)
        if not terminal:
            continue
        label = terminal.get("extension") or terminal.get("model") or str(index)
        if require_crm_fields:
            _validate_crm_terminal_fields(terminal, label)
        terminals.append(terminal)
    return terminals


def apply_structured_connectivity(result: ImportResult, connectivity: dict[str, str]) -> None:
    if not connectivity:
        return

    internet_type = _normalize_internet_type(connectivity.get("type", ""))
    if internet_type:
        result.internet_tipo = internet_type

    provider = _normalize_provider_value(connectivity.get("provider", ""))
    if provider:
        result.internet_proveedor = provider

    speed = _normalize_speed(connectivity.get("speed", "")) or connectivity.get("speed", "").upper()
    if speed:
        result.internet_velocidad = speed

    router_model = connectivity.get("router_model", "")
    if router_model:
        result.router_modelo = _detect_router_model(router_model) or router_model

    backup_model = connectivity.get("backup_model", "")
    if backup_model:
        result.backup_modelo = _detect_backup_model(backup_model) or backup_model

    ont_model = connectivity.get("ont_model", "")
    if ont_model:
        result.ont_modelo = _detect_ont_model(ont_model, result.internet_proveedor) or ont_model

    if not result.internet_tipo:
        inferred = _infer_internet_type(
            " ".join(
                value
                for value in (
                    result.internet_tipo,
                    result.internet_proveedor,
                    result.backup_modelo,
                    result.ont_modelo,
                )
                if value
            ),
            has_backup_device=bool(result.backup_modelo),
            router_model=result.router_modelo,
        )
        if inferred:
            result.internet_tipo = inferred


def _validate_work_order_identity_fields(normalized: dict) -> None:
    """Cliente, CIF, sede y direccion son obligatorios para importar una OT."""
    missing: list[str] = []
    if not normalized.get("cliente"):
        missing.append("cliente (customer.fullname)")
    if not normalized.get("cif"):
        missing.append("CIF (customer.document)")
    if not normalized.get("sede"):
        missing.append("sede (sede.name)")
    if not normalized.get("direccion"):
        missing.append("direccion (sede.address)")
    if missing:
        raise CommsError("La OT no incluye campos obligatorios: " + ", ".join(missing))


def import_result_from_json_payload(payload: dict, *, work_order_id: str = "") -> ImportResult:
    normalized = normalize_work_order_payload(payload)
    _validate_work_order_identity_fields(normalized)
    resolved_work_order_id = (
        normalized.get("work_order_id")
        or extract_work_order_id(work_order_id)
        or work_order_id
        or extract_work_order_id(str(payload))
    )

    products = normalize_products(normalized.get("products") or [])
    terminals_raw = normalized.get("terminals") or []
    explicit_terminals = parse_terminals_from_payload(
        terminals_raw,
        require_crm_fields=bool(terminals_raw),
    )

    if not products and not explicit_terminals:
        who = normalized.get("cliente") or ""
        where = normalized.get("sede") or ""
        localizacion = f" ({who} / {where})" if who or where else ""
        raise CommsError(
            f"La OT{localizacion} no tiene ningún equipo/producto cargado en comms "
            "(la lista de equipos llegó vacía). No es un fallo de esta web: "
            "avisa a quien gestiona la OT en comms para que añada los productos "
            "(router, ONT, teléfonos...) antes de volver a importar."
        )

    result = map_offer_to_form(
        products,
        cliente=normalized.get("cliente", ""),
        cif=normalized.get("cif", ""),
        sede=normalized.get("sede", ""),
        direccion=normalized.get("direccion", ""),
        connectivity_text=normalized.get("connectivity_text", ""),
        work_order_id=resolved_work_order_id,
    )
    apply_structured_connectivity(result, normalized.get("connectivity_structured") or {})
    offer_terminals = list(result.terminals)

    if explicit_terminals:
        dect_bases = normalized.get("dect_bases") or []
        if dect_bases:
            _assign_dect_bases_to_handsets(explicit_terminals, dect_bases, [])
        result.terminals = list(explicit_terminals)
        seen = {(t.get("model"), t.get("extension"), t.get("serial")) for t in result.terminals}
        for terminal in offer_terminals:
            key = (terminal.get("model"), terminal.get("extension"), terminal.get("serial"))
            if key not in seen:
                result.terminals.append(terminal)
                seen.add(key)

    glpi_entity_id = normalized.get("glpi_entity_id", "")
    if glpi_entity_id:
        result.glpi_entity_id = glpi_entity_id

    return result
