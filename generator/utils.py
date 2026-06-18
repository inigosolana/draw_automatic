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


def normalize_person_name(name: str) -> str:
    """Normaliza nombre para comparar sin depender del orden apellido/nombre."""
    text = str(name or "").strip().lower()
    parts = text.split()
    if len(parts) >= 2:
        return " ".join(sorted(parts))
    return text


def technician_is_admin(technician: dict | None, admin_users: set[str]) -> bool:
    if not technician:
        return False
    for key in ("name", "username"):
        if normalize_person_name(str(technician.get(key) or "")) in admin_users:
            return True
    return False
