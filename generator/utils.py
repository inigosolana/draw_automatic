from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Zona horaria de la aplicación: las fechas se muestran en hora de Madrid,
# independientemente de la zona del contenedor. Requiere el paquete `tzdata`.
try:
    MADRID_TZ = ZoneInfo("Europe/Madrid")
except ZoneInfoNotFoundError:  # pragma: no cover - fallback si falta tzdata
    MADRID_TZ = timezone.utc


def now_madrid() -> datetime:
    """Fecha/hora actual en Madrid (con tzinfo)."""
    return datetime.now(MADRID_TZ)


def dedupe_preserving_order(items: list[str]) -> list[str]:
    """Quita duplicados conservando el orden de primera aparición (O(n))."""
    return list(dict.fromkeys(items))


def is_safe_redirect(url: str) -> bool:
    """Solo permite rutas internas relativas (sin dominio ni esquema)."""
    if not url:
        return False
    # Rechaza backslashes ('/\evil.com' que algunos navegadores normalizan a '//')
    # y rutas protocol-relative ('//evil.com') → evita open-redirect.
    if "\\" in url or url.startswith("//"):
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
    if "," in text:
        surname, given = (part.strip() for part in text.split(",", 1))
        if surname and given:
            text = f"{given} {surname}"
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    parts = text.split()
    if len(parts) >= 2:
        return " ".join(sorted(parts))
    return text


def normalized_admin_users(admin_users: set[str]) -> set[str]:
    return {normalize_person_name(name) for name in admin_users}


def technician_is_admin(technician: dict | None, admin_users: set[str]) -> bool:
    if not technician:
        return False
    allowed = normalized_admin_users(admin_users)
    for key in ("name", "username"):
        if normalize_person_name(str(technician.get(key) or "")) in allowed:
            return True
    return False
