from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

FIELD_LABELS = {
    "cliente": "Cliente",
    "cif": "CIF",
    "sede": "Sede",
    "direccion": "Dirección",
}

_STOPWORDS = frozenset({
    "sl", "sa", "slu", "sau", "the", "de", "del", "la", "las", "los", "y", "e",
    "sede", "empresa", "oficina", "local",
})


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFD", (value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def _clean_cif(value: str) -> str:
    return re.sub(r"\s+", "", (value or "")).upper()


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[\s,.-]+", _normalize(value))
        if len(token) > 2 and token not in _STOPWORDS
    }


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


def _site_score(site: dict, imported_sede: str, imported_address: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    site_name = _normalize(site.get("nombre", ""))
    site_address = _normalize(site.get("direccion", ""))
    target_site = _normalize(imported_sede)
    target_address = _normalize(imported_address)

    if target_site and site_name and (target_site in site_name or site_name in target_site):
        score += 20
        reasons.append("sede parecida")

    for token in re.split(r"[\s,.-]+", target_address):
        if len(token) <= 3:
            continue
        if token in site_address or token in site_name:
            score += 2
            if "dirección" not in reasons:
                reasons.append("dirección")

    return score, reasons


def _customer_score(customer: dict, target_cif: str, target_client: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    customer_cif = _clean_cif(customer.get("cif", ""))
    customer_name = _normalize(customer.get("nombre", ""))

    if target_cif and customer_cif and target_cif == customer_cif:
        return 100, ["CIF exacto"]

    if not target_client or not customer_name:
        return 0, []

    if target_client == customer_name:
        score += 70
        reasons.append("nombre exacto")
    elif target_client in customer_name or customer_name in target_client:
        score += 45
        reasons.append("nombre parecido")
    else:
        overlap = _tokens(target_client) & _tokens(customer_name)
        if overlap:
            score += min(36, len(overlap) * 10)
            reasons.append("palabras comunes")
        ratio = SequenceMatcher(None, target_client, customer_name).ratio()
        if ratio >= 0.55:
            score += int(ratio * 35)
            reasons.append("nombre similar")

    return score, reasons


def find_glpi_suggestions(imported: dict, catalog: list[dict], *, limit: int = 5) -> list[dict]:
    """Return ranked GLPI province/client/site candidates similar to imported data."""
    original = {
        "cliente": str(imported.get("cliente") or "").strip(),
        "cif": str(imported.get("cif") or "").strip(),
        "sede": str(imported.get("sede") or "").strip(),
        "direccion": str(imported.get("direccion") or "").strip(),
    }
    if not catalog:
        return []

    target_cif = _clean_cif(original["cif"])
    target_client = _normalize(original["cliente"])
    candidates: list[dict] = []

    for province in catalog:
        prov_name = str(province.get("nombre") or "").strip()
        for customer in province.get("clientes") or []:
            cust_score, cust_reasons = _customer_score(customer, target_cif, target_client)
            if cust_score < 12:
                continue

            sites = customer.get("sedes") or []
            if not sites:
                continue

            for site in sites:
                site_sc, site_reasons = _site_score(site, original["sede"], original["direccion"])
                total = cust_score + site_sc
                if total < 15:
                    continue
                glpi_direccion = str(site.get("direccion") or customer.get("direccion") or "").strip()
                merged_address, _ = _pick_address(original["direccion"], glpi_direccion)
                reasons = list(dict.fromkeys(cust_reasons + site_reasons))
                candidates.append(
                    {
                        "score": total,
                        "province": prov_name,
                        "cliente": str(customer.get("nombre") or "").strip(),
                        "cif": str(customer.get("cif") or "").strip(),
                        "sede": str(site.get("nombre") or "").strip(),
                        "direccion": merged_address or glpi_direccion or original["direccion"],
                        "glpi_entity_id": str(site.get("id") or ""),
                        "reasons": reasons,
                    }
                )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    seen: set[str] = set()
    unique: list[dict] = []
    for item in candidates:
        key = item["glpi_entity_id"]
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _match_confidence(cif_match: bool, cust_score: int, site_score: int) -> str:
    if cif_match:
        return "high"
    if cust_score >= 45 and site_score >= 8:
        return "high"
    if cust_score >= 45 and site_score >= 0:
        return "low"
    if cust_score >= 25:
        return "low"
    return "none"


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
        "confidence": "none",
        "glpi_entity_id": "",
        "cliente": original["cliente"],
        "cif": original["cif"],
        "sede": original["sede"],
        "direccion": original["direccion"],
        "corrections": [],
        "suggestions": [],
        "message": "",
    }
    if not catalog:
        result["message"] = "GLPI no disponible para comparar datos."
        return result

    suggestions = find_glpi_suggestions(imported, catalog, limit=5)
    result["suggestions"] = suggestions

    target_cif = _clean_cif(original["cif"])
    target_client = _normalize(original["cliente"])

    best: dict | None = None
    best_confidence = "none"

    for province in catalog:
        for customer in province.get("clientes") or []:
            customer_cif = _clean_cif(customer.get("cif", ""))
            customer_name = _normalize(customer.get("nombre", ""))
            cif_match = bool(target_cif and customer_cif and target_cif == customer_cif)
            cust_score, _ = _customer_score(customer, target_cif, target_client)
            name_match = bool(
                target_client
                and customer_name
                and (target_client in customer_name or customer_name in target_client)
            )
            if not cif_match and not name_match and cust_score < 25:
                continue

            sites = customer.get("sedes") or []
            best_site = sites[0] if sites else None
            best_site_score = -1
            for site in sites:
                score, _ = _site_score(site, original["sede"], original["direccion"])
                if score > best_site_score:
                    best_site_score = score
                    best_site = site

            confidence = _match_confidence(cif_match, 100 if cif_match else cust_score, best_site_score)
            if confidence == "none":
                continue

            candidate = {
                "province": str(province.get("nombre") or "").strip(),
                "customer": customer,
                "site": best_site,
                "site_score": best_site_score,
                "confidence": confidence,
                "cif_match": cif_match,
                "cust_score": 100 if cif_match else cust_score,
            }
            if best is None or candidate["cust_score"] + candidate["site_score"] > best["cust_score"] + best["site_score"]:
                best = candidate
                best_confidence = confidence

    if best is None or best_confidence != "high":
        if suggestions:
            result["confidence"] = "low" if suggestions[0]["score"] >= 20 else "none"
            result["message"] = (
                "No hay coincidencia clara en GLPI. Elige una opción similar abajo "
                "o selecciona provincia, cliente y sede manualmente."
            )
        else:
            result["confidence"] = "none"
            result["message"] = (
                "No se ha encontrado el cliente en GLPI. "
                "Selecciona provincia, cliente y sede manualmente."
            )
        return result

    customer = best["customer"]
    best_site = best["site"]
    glpi_cliente = str(customer.get("nombre") or "").strip()
    glpi_cif = str(customer.get("cif") or "").strip()
    glpi_sede = str(best_site.get("nombre") or "").strip() if best_site else original["sede"]
    glpi_direccion = (
        str(best_site.get("direccion") or customer.get("direccion") or "").strip()
        if best_site
        else ""
    )
    if original["direccion"]:
        # La direccion del CRM/OT suele ser mas fiable que la de GLPI.
        merged_address = original["direccion"]
        address_source = "CRM"
    else:
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
    if original["direccion"] and glpi_direccion and _normalize(original["direccion"]) != _normalize(glpi_direccion):
        address_correction = _maybe_correction(
            "direccion",
            glpi_direccion,
            original["direccion"],
            "CRM",
        )
    else:
        address_correction = _maybe_correction(
            "direccion",
            original["direccion"] or glpi_direccion,
            merged["direccion"],
            address_source or "GLPI",
        )
    if address_correction:
        corrections.append(address_correction)

    # Si hay otra opción casi igual de buena, bajar confianza y mostrar sugerencias
    if len(suggestions) > 1 and suggestions[0]["score"] - suggestions[1]["score"] <= 8:
        result.update(
            {
                "confidence": "low",
                "matched": False,
                "glpi_entity_id": "",
                "cliente": original["cliente"],
                "cif": original["cif"],
                "sede": original["sede"],
                "direccion": original["direccion"],
                "corrections": [],
                "suggestions": suggestions,
                "message": (
                    "Hay varias coincidencias posibles en GLPI. "
                    "Revisa las opciones sugeridas o elige manualmente."
                ),
            }
        )
        return result

    message = (
        f"GLPI: {merged['cliente']} / {merged['sede']}"
        if best_site
        else f"GLPI: cliente {merged['cliente']} encontrado. Selecciona la sede manualmente."
    )
    if (
        original["direccion"]
        and glpi_direccion
        and _normalize(original["direccion"]) != _normalize(glpi_direccion)
    ):
        message += " Dirección del CRM aplicada; GLPI tenía otra distinta."

    result.update(
        {
            "matched": True,
            "confidence": "high",
            "glpi_entity_id": str(best_site.get("id") or "") if best_site else "",
            "cliente": merged["cliente"],
            "cif": merged["cif"],
            "sede": merged["sede"],
            "direccion": merged["direccion"],
            "corrections": corrections,
            "suggestions": [],
            "message": message,
        }
    )
    return result
