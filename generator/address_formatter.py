from __future__ import annotations

import re
import unicodedata

_CITY_POSTCODE_SUFFIX = re.compile(
    r"([.,]\s*|\s+)"
    r"(?:(?P<prefix>[^.,\d]+?)\s*,\s*)?"
    r"(?P<city>[A-Za-zÁÉÍÓÚáéíóúñÑ'’\-\s]+?)\s+"
    r"(?P<cp>\d{5})\s*"
    r"(?:,\s*(?P<province>[A-Za-zÁÉÍÓÚáéíóúñÑ'’\-\s]+))?\s*$",
    flags=re.UNICODE,
)

_REDUNDANT_CALLE_PREFIX = re.compile(
    r"^calle\s+(?=(?:rúa|rua|avenida|av\.?|plaza|paseo|carretera|traves[ií]a|pol[ií]gono)\b)",
    flags=re.IGNORECASE,
)

_STREET_TYPE_LABELS = {
    "rua": "Rúa",
    "rúa": "Rúa",
    "calle": "Calle",
    "avenida": "Avenida",
    "av": "Av.",
    "plaza": "Plaza",
    "paseo": "Paseo",
    "carretera": "Carretera",
    "travesia": "Travesía",
    "travesía": "Travesía",
    "poligono": "Polígono",
    "polígono": "Polígono",
}


def _collapse_whitespace(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _strip_city_postcode_suffix(text: str) -> str:
    match = _CITY_POSTCODE_SUFFIX.search(text)
    if not match:
        return text
    return text[: match.start()].strip(" ,.;")


def _title_street_type(text: str) -> str:
    match = re.match(r"^(\S+)\s*(.*)$", text, flags=re.UNICODE)
    if not match:
        return text
    first = match.group(1)
    rest = match.group(2).strip()
    key = re.sub(r"[^\wáéíóúñ]", "", first.lower())
    label = _STREET_TYPE_LABELS.get(key)
    if not label:
        return text
    if first.endswith(",") and rest:
        return f"{label}, {rest}"
    return f"{label} {rest}".strip() if rest else label


def normalize_street_address(raw: str) -> str:
    """Return a single-line street address without duplicated city/postcode tails."""
    text = _collapse_whitespace(raw)
    if not text:
        return ""

    text = _strip_city_postcode_suffix(text)
    text = _REDUNDANT_CALLE_PREFIX.sub("", text).strip()
    text = _collapse_whitespace(text)
    text = _title_street_type(text)
    return text.strip(" ,.;")


def addresses_equivalent(left: str, right: str) -> bool:
    def key(value: str) -> str:
        normalized = normalize_street_address(value)
        folded = unicodedata.normalize("NFKD", normalized)
        folded = "".join(char for char in folded if not unicodedata.combining(char))
        return folded.casefold()

    return key(left) == key(right)
