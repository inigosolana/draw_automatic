from __future__ import annotations

from urllib.parse import urlparse


def is_safe_redirect(url: str) -> bool:
    """Solo permite rutas internas relativas (sin dominio ni esquema)."""
    if not url:
        return False
    parsed = urlparse(url)
    return not parsed.netloc and not parsed.scheme and url.startswith("/")


def positive_integer(value: object, field_name: str) -> int:
    text = str(value or "").strip()
    if not text.isdigit() or int(text) <= 0:
        raise ValueError(f"El campo '{field_name}' debe ser un ID entero positivo.")
    return int(text)
