from __future__ import annotations

import re

from .offer_mapper import (
    ImportResult,
    OfferProduct,
    extract_work_order_id,
    map_offer_to_form,
    parse_extension_tokens,
    parse_product_lines,
    strip_inline_extensions,
    strip_puerto_token,
)
from .utils import dedupe_preserving_order


OT_NUMBER_PATTERN = re.compile(r"\bOT0*(\d+)\b", re.IGNORECASE)
CIF_PATTERN = re.compile(r"\b[A-Z]\d{8}\b")
INSTALLATION_ADDRESS_PATTERN = re.compile(
    r"direcci[oó]n de instalaci[oó]n\s*(?:\(([^)]+)\))?\s*:?\s*$",
    re.IGNORECASE,
)
PRODUCT_LINE_PATTERN = re.compile(r"producto\s*:\s*(.+)$", re.IGNORECASE)
SERVICE_LINE_PATTERN = re.compile(r"servicio\s*:\s*(.+)$", re.IGNORECASE)
SERVICIO_PRODUCT_LINE_PATTERN = re.compile(
    r"Servicio:\s*(?P<servicio>.+?)\s+Producto:\s*(?P<producto>.+)$",
    re.IGNORECASE,
)
VOIP_SERVICE_EXTENSION_PATTERN = re.compile(
    r"puestos?\s*voip\s*-\s*(\d{2,6})",
    re.IGNORECASE,
)
FIBER_PRODUCT_PATTERN = re.compile(r"fibra\s+pro\s+max", re.IGNORECASE)


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "").strip())


def _value_on_next_line(lines: list[str], index: int) -> str:
    if index + 1 >= len(lines):
        return ""
    candidate = _clean_line(lines[index + 1])
    if not candidate or _looks_like_label(candidate):
        return ""
    return candidate


def _looks_like_label(line: str) -> bool:
    lowered = line.lower().rstrip(":")
    labels = (
        "cif",
        "nombre del cliente",
        "prioridad",
        "número ot",
        "numero ot",
        "control técnico",
        "configurador noc",
        "técnico 1",
        "tecnico 1",
        "técnico 2",
        "comercial",
        "contacto de sede",
        "teléfono",
        "telefono",
        "mismo",
        "número administrativo",
        "numero administrativo",
        "direcciones de fibra",
        "actuación",
        "actuacion",
        "empresa instaladora",
        "equipos incluidos",
        "servicio",
        "código ean",
        "codigo ean",
        "nombre del producto",
        "configuración",
        "configuracion",
        "trabajos a realizar",
        "velocidad ftth",
        "latencia",
        "comprobaciones",
        "cobertura",
        "diagrama de red",
        "cierre ot conforme",
        "adjuntar archivos",
        "sí",
        "si",
        "no",
        "--- selecciona",
    )
    if lowered in labels:
        return True
    if lowered.endswith(":") and len(lowered) < 60:
        return True
    return False


def _extract_cif(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if line.lower() in {"cif", "cif:"}:
            inline = _value_on_next_line(lines, index)
            if inline:
                return inline.upper()
        match = CIF_PATTERN.search(line)
        if match and line.lower().startswith("cif"):
            return match.group(0).upper()
    for line in lines:
        match = CIF_PATTERN.search(line)
        if match:
            return match.group(0).upper()
    return ""


def _extract_client_name(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        lowered = line.lower()
        if lowered.startswith("nombre del cliente"):
            parts = re.split(r":\s*", line, maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                return parts[1].strip()
            return _value_on_next_line(lines, index)
    return ""


def _extract_work_order_number(lines: list[str], full_text: str) -> str:
    for index, line in enumerate(lines):
        if "número ot" in line.lower() or "numero ot" in line.lower():
            parts = re.split(r":\s*", line, maxsplit=1)
            if len(parts) > 1:
                match = OT_NUMBER_PATTERN.search(parts[1])
                if match:
                    return match.group(1)
            match = OT_NUMBER_PATTERN.search(_value_on_next_line(lines, index))
            if match:
                return match.group(1)
    match = OT_NUMBER_PATTERN.search(full_text)
    return match.group(1) if match else ""


def _extract_installation(lines: list[str]) -> tuple[str, str]:
    sede = ""
    direccion = ""
    for index, line in enumerate(lines):
        header = INSTALLATION_ADDRESS_PATTERN.search(line)
        if not header:
            continue
        sede = (header.group(1) or "").strip()
        for offset in range(1, 4):
            if index + offset >= len(lines):
                break
            candidate = _clean_line(lines[index + offset])
            if not candidate or _looks_like_label(candidate):
                continue
            if candidate.lower().startswith("contacto de sede"):
                break
            if re.search(r"\d{5}", candidate) or re.search(r"calle|avenida|av\.|plaza|paseo|pol[ií]gono", candidate, re.I):
                direccion = candidate
                break
        break
    if sede and " - " in sede:
        short_name = sede.split(" - ", 1)[1].strip()
        if short_name:
            sede = short_name
    return sede, direccion


def _extract_servicio_lines(lines: list[str]) -> list[str]:
    services: list[str] = []
    for line in lines:
        match = SERVICE_LINE_PATTERN.search(line)
        if match:
            name = match.group(1).strip()
            if name:
                services.append(name)
    return services


def _extensions_from_servicio(servicio: str) -> list[str]:
    extensions: list[str] = []
    for match in VOIP_SERVICE_EXTENSION_PATTERN.finditer(servicio or ""):
        extensions.append(match.group(1))
    extensions.extend(parse_extension_tokens(servicio))
    return dedupe_preserving_order(extensions)


def _product_block_extensions(block: list[str]) -> list[str]:
    extensions: list[str] = []
    in_config = False
    for line in block:
        lowered = line.lower()
        if lowered.startswith("configuraci"):
            in_config = True
            continue
        found = parse_extension_tokens(line)
        if found:
            extensions.extend(found)
            continue
        if in_config and re.fullmatch(r"\d{2,6}", line.strip()):
            extensions.append(line.strip())
    return dedupe_preserving_order(extensions)


def _extract_products(lines: list[str]) -> list[OfferProduct]:
    products: list[OfferProduct] = []
    pending_servicio = ""

    for index, line in enumerate(lines):
        combined = SERVICIO_PRODUCT_LINE_PATTERN.search(line)
        if combined:
            pending_servicio = ""
            servicio = combined.group("servicio").strip()
            name = combined.group("producto").strip()
            name, puerto = strip_puerto_token(name)
            name, inline_extensions = strip_inline_extensions(name)
            extensions = _extensions_from_servicio(servicio) or list(inline_extensions)
            products.append(OfferProduct(name=name, quantity=1, extensions=extensions, puerto=puerto))
            continue

        servicio_match = SERVICE_LINE_PATTERN.search(line)
        if servicio_match and "producto:" not in line.lower():
            pending_servicio = servicio_match.group(1).strip()
            continue

        product_match = PRODUCT_LINE_PATTERN.search(line)
        if not product_match:
            continue

        end = len(lines)
        for next_index in range(index + 1, len(lines)):
            if (
                PRODUCT_LINE_PATTERN.search(lines[next_index])
                or SERVICIO_PRODUCT_LINE_PATTERN.search(lines[next_index])
                or (
                    SERVICE_LINE_PATTERN.search(lines[next_index])
                    and "producto:" not in lines[next_index].lower()
                )
            ):
                end = next_index
                break

        name = product_match.group(1).strip()
        name, puerto = strip_puerto_token(name)
        name, inline_extensions = strip_inline_extensions(name)
        extensions = list(inline_extensions)
        if pending_servicio:
            extensions = _extensions_from_servicio(pending_servicio) or extensions
            pending_servicio = ""
        extensions.extend(_product_block_extensions(lines[index + 1 : end]))
        deduped = dedupe_preserving_order(extensions)
        products.append(OfferProduct(name=name, quantity=1, extensions=deduped, puerto=puerto))

    return products


def _extract_connectivity_text(lines: list[str], full_text: str) -> str:
    chunks: list[str] = []
    capture = False
    for line in lines:
        lowered = line.lower()
        if lowered.startswith("direcciones de fibra"):
            capture = True
        if lowered.startswith("comprobaciones"):
            capture = True
        if lowered.startswith("diagrama de red"):
            break
        if capture:
            chunks.append(line)
        if lowered.startswith("trabajos a realizar"):
            capture = True
            chunks.append(line)
    if not chunks:
        chunks = lines
    blob = " ".join(chunks)
    if FIBER_PRODUCT_PATTERN.search(full_text):
        blob += " 1 GB Fibra PRO Max"
    return blob


def _extract_voip_seats(text: str) -> int:
    match = re.search(r"(\d+)\s+puestos?\s+voip", text, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def parse_work_order_paste(text: str) -> ImportResult:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("No se ha pegado ningún texto de la orden de trabajo.")

    lines = [_clean_line(line) for line in raw.splitlines() if _clean_line(line)]
    full_text = "\n".join(lines)

    cif = _extract_cif(lines)
    cliente = _extract_client_name(lines)
    work_order_id = _extract_work_order_number(lines, full_text) or extract_work_order_id(raw)
    sede, direccion = _extract_installation(lines)
    servicio_lines = _extract_servicio_lines(lines)
    connectivity_text = _extract_connectivity_text(lines, full_text)
    if servicio_lines:
        connectivity_text = f"{connectivity_text} {' '.join(servicio_lines)}"
    product_entries = _extract_products(lines)
    if product_entries:
        products = product_entries
    else:
        fallback_names = [
            line
            for line in lines
            if line and not _looks_like_label(line) and len(line) < 120 and not CIF_PATTERN.fullmatch(line)
        ]
        products = parse_product_lines("\n".join(fallback_names)) if fallback_names else []
    result = map_offer_to_form(
        products,
        cliente=cliente,
        cif=cif,
        sede=sede,
        direccion=direccion,
        connectivity_text=connectivity_text,
        work_order_id=work_order_id,
    )

    voip_seats = _extract_voip_seats(full_text)
    if voip_seats and len(result.terminals) < voip_seats:
        result.warnings.append(
            f"La OT indica {voip_seats} puestos VOIP pero solo se han detectado {len(result.terminals)} terminales."
        )

    if work_order_id and not result.work_order_id:
        result.work_order_id = work_order_id

    if not products:
        result.warnings.append("No se han encontrado lineas 'Producto:' en el texto pegado.")

    return result
