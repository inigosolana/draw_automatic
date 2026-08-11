from __future__ import annotations

import re
import unicodedata

# Abreviatura de proveedor usada en el nombre de host (FTTH_<ABBR>_...), tal como
# aparece en el Zabbix real. Se estandariza aquí para no repetir el caos actual
# (AIR/AIRE, MM/MASMOVIL, etc.).
PROVIDER_ABBR = {
    "SARENET": "SAR",
    "AIRE": "AIR",
    "ADAMO": "ADA",
    "MASMOVIL": "MM",
    "MAS MOVIL": "MM",
    "ORANGE": "ORA",
    "SARENET ORANGE": "ORA",
    "EUSKALTEL": "EUS",
    "MOVISTAR": "MOV",
    "VODAFONE": "VOD",
    "DUAL": "DUAL",  # prefijo especial para FIBRA DUAL (nombre FTTH_DUAL_...)
}

# Abreviatura del tipo de backup para el nombre BACKUP_<ABBR>_...
BACKUP_ABBR = {
    "TELTONIKA": "TEL",
    "KITE": "KIT",
    "WAP LTE": "WAP",
    "WAP": "WAP",
}


def strip_cidr(ip: str) -> str:
    return ip.split("/")[0].strip()


def map_yeastar_provider(raw: str) -> str:
    """Normaliza el proveedor tal como viene en Yeastar (p. ej. 'Citelia-Aire')
    al valor de proveedor de fibra usado en el tag PROVEEDOR."""
    s = re.sub(r"^(citelia|ausarta)\s*-\s*", "", (raw or "").strip(), flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip().upper()
    aliases = {
        "MASMOVIL": "MAS MOVIL",
        "TELEFONICA": "MOVISTAR",
    }
    return aliases.get(s, s)


def provider_tag_value(provider: str) -> str:
    """Valor canónico (mayúsculas) para el tag PROVEEDOR."""
    return re.sub(r"\s+", " ", provider or "").strip().upper()


def provider_abbr(provider: str) -> str:
    key = provider_tag_value(provider)
    if key in PROVIDER_ABBR:
        return PROVIDER_ABBR[key]
    # Fallback: primeras 3 letras alfanuméricas en mayúscula.
    letters = re.sub(r"[^A-Z0-9]", "", key)
    return letters[:3] or "GEN"


def backup_abbr(backup_tipo: str) -> str:
    key = re.sub(r"\s+", " ", backup_tipo or "").strip().upper()
    if key in BACKUP_ABBR:
        return BACKUP_ABBR[key]
    letters = re.sub(r"[^A-Z0-9]", "", key)
    return letters[:3] or "KIT"


def _name_part(text: str) -> str:
    """Normaliza un trozo del nombre de host a MAYÚSCULAS con guiones bajos.

    Zabbix admite en host name letras, dígitos, espacios, puntos, guiones y
    subrayados. Aquí se colapsa todo lo demás a '_' para dejar nombres limpios
    tipo AUTOMOCION_ESPINOSA_RAOS_9.
    """
    text = unicodedata.normalize("NFKD", (text or "").strip().upper())
    text = "".join(c for c in text if not unicodedata.combining(c))  # ñ->N, í->I...
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def build_router_hostname(
    provider: str, cliente: str, sede: str, localidad: str = "", calle: str = ""
) -> str:
    """Nombre unificado: FTTH_<PROV>_<CLIENTE>_<SEDE>_<LOCALIDAD>_<CALLE> (MAYÚSCULAS)."""
    parts = [
        p
        for p in (
            "FTTH",
            provider_abbr(provider),
            _name_part(cliente),
            _name_part(sede),
            _name_part(localidad),
            _name_part(calle),
        )
        if p
    ]
    return "_".join(parts)[:128]


def build_lte_hostname(
    provider: str, cliente: str, sede: str, localidad: str = "", calle: str = ""
) -> str:
    """Nombre unificado LTE/4G: LTE_<PROV>_<CLIENTE>_<SEDE>_<LOCALIDAD>_<CALLE>."""
    parts = [
        p
        for p in (
            "LTE",
            provider_abbr(provider),
            _name_part(cliente),
            _name_part(sede),
            _name_part(localidad),
            _name_part(calle),
        )
        if p
    ]
    return "_".join(parts)[:128]


def build_backup_hostname(
    backup_tipo: str, cliente: str, sede: str, localidad: str = "", calle: str = ""
) -> str:
    """Nombre unificado: BACKUP_<TIPO>_<CLIENTE>_<SEDE>_<LOCALIDAD>_<CALLE> (MAYÚSCULAS)."""
    parts = [
        p
        for p in (
            "BACKUP",
            backup_abbr(backup_tipo),
            _name_part(cliente),
            _name_part(sede),
            _name_part(localidad),
            _name_part(calle),
        )
        if p
    ]
    return "_".join(parts)[:128]


def suggest_zabbix_host_name(cliente: str, sede: str) -> str:
    base = f"{cliente}-{sede}".strip("-")
    slug = re.sub(r"[^a-zA-Z0-9.-]", "-", base)
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    return slug[:128] or "host"


def suggest_zabbix_visible_name(cliente: str, sede: str) -> str:
    cliente = cliente.strip()
    sede = sede.strip()
    if cliente and sede:
        return f"{cliente} - {sede}"
    return cliente or sede
