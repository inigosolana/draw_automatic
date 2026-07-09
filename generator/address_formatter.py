from __future__ import annotations

import re
import unicodedata

_CITY_POSTCODE_SUFFIX = re.compile(
    r"([.,]\s*|\s+)"
    r"(?:(?P<prefix>[^.,\d]{1,60}?)\s*,\s*)?"
    r"(?P<city>[A-Za-zÁÉÍÓÚáéíóúñÑ'’\-\s]{1,60}?)\s+"
    r"(?P<cp>\d{5})\s*"
    r"(?:,\s*(?P<province>[A-Za-zÁÉÍÓÚáéíóúñÑ'’\-\s]{1,60}))?\s*$",
    flags=re.UNICODE,
)


def _collapse_whitespace(value: str) -> str:
    return " ".join((value or "").split()).strip()


def to_glpi_ascii(value: str) -> str:
    """GLPI-friendly text: no accents and n instead of n-tilde."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_marks.replace("ñ", "n").replace("Ñ", "N")


_SUFFIX_SEARCH_WINDOW = 300


def _strip_city_postcode_suffix(text: str) -> str:
    # The city/postcode suffix is always at the end; only scan a bounded tail
    # to avoid costly backtracking on very long, user-controlled inputs.
    offset = max(0, len(text) - _SUFFIX_SEARCH_WINDOW)
    match = _CITY_POSTCODE_SUFFIX.search(text[offset:])
    if not match:
        return text
    return text[: offset + match.start()].strip(" ,.;")


def normalize_street_address(raw: str) -> str:
    """Return a single-line street address without city/postcode tails."""
    text = _collapse_whitespace(raw)
    if not text:
        return ""

    text = _strip_city_postcode_suffix(text)
    text = _collapse_whitespace(text)
    return to_glpi_ascii(text.strip(" ,.;"))


def addresses_equivalent(left: str, right: str) -> bool:
    return to_glpi_ascii(normalize_street_address(left)).casefold() == to_glpi_ascii(
        normalize_street_address(right)
    ).casefold()
