from __future__ import annotations

import re


def strip_cidr(ip: str) -> str:
    return ip.split("/")[0].strip()


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
