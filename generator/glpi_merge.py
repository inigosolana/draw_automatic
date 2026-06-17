from __future__ import annotations

import re
import unicodedata


FIELD_LABELS = {
    "cliente": "Cliente",
    "cif": "CIF",
    "sede": "Sede",
    "direccion": "Dirección",
}


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFD", (value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def _clean_cif(value: str) -> str:
    return re.sub(r"\s+", "", (value or "")).upper()


def _address_richness(address: str) -> int:
    score = len((address or "").strip())
    lowered = address.lower()
    if re.search(r"calle|avenida|av\.|plaza|paseo|oficina|local|pol[ií]gono|carretera", lowered):
        score += 50
    if re.search(r"\d{5}", address):
        score += 20
    return score


def _pick_address(offer_address: str, glpi_address: str) -> tuple[str, str]:
    offer = (offer_address or "").strip()
    glpi = (glpi_address or "").strip()
    if not offer:
        return glpi, "GLPI"
    if not glpi:
        return offer, "oferta"
    if _normalize(offer) == _normalize(glpi):
        return offer, ""
    if _address_richness(offer) > _address_richness(glpi):
        return offer, "oferta"
    return glpi, "GLPI"


def _site_score(site: dict, imported_sede: str, imported_address: str) -> int:
    score = 0
    site_name = _normalize(site.get("nombre", ""))
    site_address = _normalize(site.get("direccion", ""))
    target_site = _normalize(imported_sede)
    target_address = _normalize(imported_address)

    if target_site and site_name and (target_site in site_name or site_name in target_site):
        score += 20

    for token in re.split(r"[\s,.-]+", target_address):
        if len(token) <= 3:
            continue
        if token in site_address or token in site_name:
            score += 2
    return score


def _maybe_correction(field: str, before: str, after: str, source: str) -> dict | None:
    if not after:
        return None
    if _normalize(before) == _normalize(after):
        return None
    if field == "cif" and _clean_cif(before) == _clean_cif(after):
        return None
    return {
        "field": field,
        "label": FIELD_LABELS.get(field, field),
        "before": before.strip(),
        "after": after.strip(),
        "source": source,
    }


def merge_import_with_glpi(imported: dict, catalog: list[dict]) -> dict:
    original = {
        "cliente": str(imported.get("cliente") or "").strip(),
        "cif": str(imported.get("cif") or "").strip(),
        "sede": str(imported.get("sede") or "").strip(),
        "direccion": str(imported.get("direccion") or "").strip(),
    }
    result = {
        "matched": False,
        "glpi_entity_id": "",
        "cliente": original["cliente"],
        "cif": original["cif"],
        "sede": original["sede"],
        "direccion": original["direccion"],
        "corrections": [],
        "message": "",
    }
    if not catalog:
        result["message"] = "GLPI no disponible para comparar datos."
        return result

    target_cif = _clean_cif(original["cif"])
    target_client = _normalize(original["cliente"])

    for province in catalog:
        for customer in province.get("clientes") or []:
            customer_cif = _clean_cif(customer.get("cif", ""))
            customer_name = _normalize(customer.get("nombre", ""))
            cif_match = bool(target_cif and customer_cif and target_cif == customer_cif)
            name_match = bool(
                target_client
                and customer_name
                and (target_client in customer_name or customer_name in target_client)
            )
            if not cif_match and not name_match:
                continue

            sites = customer.get("sedes") or []
            best_site = sites[0] if sites else None
            best_score = -1
            for site in sites:
                score = _site_score(site, original["sede"], original["direccion"])
                if score > best_score:
                    best_score = score
                    best_site = site

            glpi_cliente = str(customer.get("nombre") or "").strip()
            glpi_cif = str(customer.get("cif") or "").strip()
            glpi_sede = str(best_site.get("nombre") or "").strip() if best_site else original["sede"]
            glpi_direccion = str(best_site.get("direccion") or customer.get("direccion") or "").strip() if best_site else ""
            merged_address, address_source = _pick_address(original["direccion"], glpi_direccion)

            merged = {
                "cliente": glpi_cliente or original["cliente"],
                "cif": glpi_cif or original["cif"],
                "sede": glpi_sede or original["sede"],
                "direccion": merged_address or original["direccion"] or glpi_direccion,
            }

            corrections: list[dict] = []
            for field, source in (
                ("cliente", "GLPI"),
                ("cif", "GLPI"),
                ("sede", "GLPI"),
            ):
                item = _maybe_correction(field, original[field], merged[field], source)
                if item:
                    corrections.append(item)
            address_correction = _maybe_correction(
                "direccion",
                original["direccion"] or glpi_direccion,
                merged["direccion"],
                address_source or "GLPI",
            )
            if address_correction:
                corrections.append(address_correction)

            result.update(
                {
                    "matched": True,
                    "glpi_entity_id": str(best_site.get("id") or "") if best_site else "",
                    "cliente": merged["cliente"],
                    "cif": merged["cif"],
                    "sede": merged["sede"],
                    "direccion": merged["direccion"],
                    "corrections": corrections,
                    "message": (
                        f"GLPI: {merged['cliente']} / {merged['sede']}"
                        if best_site
                        else f"GLPI: cliente {merged['cliente']} encontrado. Selecciona la sede manualmente."
                    ),
                }
            )
            return result

    result["message"] = "No se ha encontrado el cliente en GLPI. Revisa cliente, CIF y sede."
    return result
