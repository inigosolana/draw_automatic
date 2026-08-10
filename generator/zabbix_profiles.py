"""Modelo real de alta de hosts de router en el Zabbix de Ausarta.

Tipos de instalación soportados (confirmados sobre los hosts reales):
- fibra         : router MikroTik de fibra. SNMP FIBRA + RouterOS BGP/V7 (según versión).
- fibra_backup  : router de fibra + equipo de backup (2 hosts).
- chateau       : CHATEAU con fibra+backup integrado (1 host). FIBRA CHATEAU + BGP V7.
- dual          : FIBRA DUAL (1 host, dos operadores). FIBRA DUAL + BGP V7.
- lte           : solo LTE/4G monitorizado (1 host, una plantilla LTE, solo SNMP).

Reglas comunes: interfaz SNMP v2 puerto 161, community por macro {$SNMP_COMMUNITY},
monitored_by=proxy. El proveedor va en tag PROVEEDOR (uno o dos en chateau/dual).
Los tipos con BGP (fibra, fibra_backup, chateau, dual) requieren detectar la versión
RouterOS; lte y backup no (solo SNMP).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .zabbix_helpers import (
    build_backup_hostname,
    build_lte_hostname,
    build_router_hostname,
    provider_tag_value,
    strip_cidr,
)


class ZabbixProfileError(ValueError):
    pass


INSTALL_TYPES = (
    ("fibra", "Fibra"),
    ("fibra_backup", "Fibra + backup"),
    ("chateau", "CHATEAU (fibra + backup integrado)"),
    ("dual", "Fibra DUAL (dos operadores)"),
    ("lte", "Solo LTE / 4G monitorizado"),
)

FIBER_PROVIDERS = (
    "AIRE",
    "ADAMO",
    "MAS MOVIL",
    "EUSKALTEL",
    "SARENET",
    "SARENET ORANGE",
    "ORANGE",
    "MOVISTAR",
    "VODAFONE",
    "PTV",
)

# Tipo de backup -> (templateid, etiqueta). Teltonika usa SU plantilla, no la de Mikrotik.
BACKUP_TYPES = (
    ("TELTONIKA", "Teltonika (Teltonika SNMP any device)"),
    ("KITE", "Kite (Mikrotik SNMP BACKUP)"),
    ("WAP LTE", "WAP LTE (Mikrotik SNMP BACKUP)"),
)

# Plantillas LTE/4G seleccionables (label, templateid).
LTE_TEMPLATES = (
    ("Mikrotik SNMP LTE HAP", "11816"),
    ("Mikrotik SNMP LTE 300Gb", "10846"),
    ("Mikrotik SNMP LTE 400Gb", "11998"),
    ("Mikrotik SNMP LTE 800Gb", "10746"),
    ("Mikrotik SNMP LTE CHATEAU 300Gb", "11996"),
    ("Mikrotik SNMP LTE CHATEAU 400Gb", "11999"),
    ("Mikrotik SNMP LTE CHATEAU 800Gb", "11997"),
    ("Mikrotik SNMP 4G AC3", "10770"),
)

# IDs reales por defecto (estables). Override por entorno ZABBIX_TEMPLATE_*.
DEFAULT_TEMPLATES = {
    "SNMP_FIBRA": "10747",
    "ROUTEROS_BGP": "11208",
    "ROUTEROS_BGP_V7": "13463",
    "SNMP_BACKUP": "10758",
    "TELTONIKA": "13483",
    "FIBRA_CHATEAU": "14924",
    "FIBRA_DUAL": "15558",
}
DEFAULT_SNMP_COMMUNITY = "ausarta@conecta"
DEFAULT_ROUTEROS_USERNAME = "Ausarta"


def _tpl(key: str) -> str:
    return os.environ.get(f"ZABBIX_TEMPLATE_{key}", "").strip() or DEFAULT_TEMPLATES[key]


def template_routeros_bgp(is_v7: bool) -> tuple[str, str]:
    if is_v7:
        return _tpl("ROUTEROS_BGP_V7"), "Template RouterOS BGP V7"
    return _tpl("ROUTEROS_BGP"), "Template RouterOS BGP"


def default_snmp_community() -> str:
    return os.environ.get("ZABBIX_DEFAULT_SNMP_COMMUNITY", "").strip() or DEFAULT_SNMP_COMMUNITY


def default_routeros_username() -> str:
    return os.environ.get("ZABBIX_ROUTEROS_USERNAME", "").strip() or DEFAULT_ROUTEROS_USERNAME


def needs_version(tipo: str) -> bool:
    """Los tipos con BGP necesitan saber la versión RouterOS (v6/v7)."""
    return tipo in ("fibra", "fibra_backup", "chateau", "dual")


def _backup_templateid(backup_tipo: str) -> tuple[str, str]:
    key = provider_tag_value(backup_tipo)
    if key == "TELTONIKA":
        return _tpl("TELTONIKA"), "Teltonika SNMP any device"
    return _tpl("SNMP_BACKUP"), "Mikrotik SNMP BACKUP"


@dataclass(frozen=True)
class ZabbixMacro:
    macro: str
    value: str
    secret: bool = False


@dataclass(frozen=True)
class ZabbixHostSpec:
    role: str
    group_role: str  # "Fibra" | "Backup" | "LTE"
    host: str
    name: str
    ip: str
    template_ids: tuple[str, ...]
    template_labels: tuple[str, ...]
    tags: tuple[tuple[str, str], ...] = ()
    macros: tuple[ZabbixMacro, ...] = ()


@dataclass(frozen=True)
class ZabbixInstallPlan:
    hosts: tuple[ZabbixHostSpec, ...]
    summary: str
    warnings: tuple[str, ...] = field(default=())


def _routeros_macros(community: str, username: str, password: str) -> tuple[ZabbixMacro, ...]:
    macros = [ZabbixMacro("{$SNMP_COMMUNITY}", community), ZabbixMacro("{$ROUTEROS_USERNAME}", username)]
    if password:
        # La contraseña del router va como macro SECRET (no legible en la UI/API).
        macros.append(ZabbixMacro("{$ROUTEROS_PASSWORD}", password, secret=True))
    return tuple(macros)


def _provider_tags(*providers: str) -> tuple[tuple[str, str], ...]:
    return tuple(("PROVEEDOR", provider_tag_value(p)) for p in providers if provider_tag_value(p))


def build_router_spec(
    *,
    cliente: str,
    sede: str,
    proveedor: str,
    router_ip: str,
    is_v7: bool,
    localidad: str = "",
    calle: str = "",
    router_username: str = "",
    router_password: str = "",
    snmp_community: str = "",
    template_key: str = "SNMP_FIBRA",
    template_label: str = "Mikrotik SNMP FIBRA",
    providers: tuple[str, ...] = (),
    name_prefix: str = "",
) -> ZabbixHostSpec:
    ip = strip_cidr(router_ip)
    if not ip:
        raise ZabbixProfileError("Indica la IP pública del router.")
    if not proveedor:
        raise ZabbixProfileError("Selecciona el proveedor de fibra.")
    community = (snmp_community or "").strip() or default_snmp_community()
    username = (router_username or "").strip() or default_routeros_username()
    bgp_id, bgp_label = template_routeros_bgp(is_v7)
    tags = _provider_tags(*(providers or (proveedor,)))
    hostname = build_router_hostname(name_prefix or proveedor, cliente, sede, localidad, calle)
    return ZabbixHostSpec(
        role="router",
        group_role="Fibra",
        host=hostname,
        name=hostname,
        ip=ip,
        template_ids=(_tpl(template_key), bgp_id),
        template_labels=(template_label, bgp_label),
        tags=tags,
        macros=_routeros_macros(community, username, router_password),
    )


def build_backup_spec(
    *,
    cliente: str,
    sede: str,
    proveedor: str,
    backup_tipo: str,
    backup_ip: str,
    localidad: str = "",
    calle: str = "",
    snmp_community: str = "",
) -> ZabbixHostSpec:
    ip = strip_cidr(backup_ip)
    if not ip:
        raise ZabbixProfileError("Indica la IP del backup.")
    community = (snmp_community or "").strip() or default_snmp_community()
    tpl_id, tpl_label = _backup_templateid(backup_tipo)
    tag_value = provider_tag_value(backup_tipo) or provider_tag_value(proveedor)
    hostname = build_backup_hostname(backup_tipo, cliente, sede, localidad, calle)
    return ZabbixHostSpec(
        role="backup",
        group_role="Backup",
        host=hostname,
        name=hostname,
        ip=ip,
        template_ids=(tpl_id,),
        template_labels=(tpl_label,),
        tags=(("PROVEEDOR", tag_value),) if tag_value else (),
        macros=(ZabbixMacro("{$SNMP_COMMUNITY}", community),),
    )


def build_lte_spec(
    *,
    cliente: str,
    sede: str,
    proveedor: str,
    lte_templateid: str,
    lte_label: str,
    ip: str,
    localidad: str = "",
    calle: str = "",
    snmp_community: str = "",
) -> ZabbixHostSpec:
    ip = strip_cidr(ip)
    if not ip:
        raise ZabbixProfileError("Indica la IP del equipo LTE/4G.")
    if not lte_templateid:
        raise ZabbixProfileError("Selecciona la plantilla LTE/4G.")
    community = (snmp_community or "").strip() or default_snmp_community()
    hostname = build_lte_hostname(proveedor, cliente, sede, localidad, calle)
    return ZabbixHostSpec(
        role="lte",
        group_role="LTE",
        host=hostname,
        name=hostname,
        ip=ip,
        template_ids=(lte_templateid,),
        template_labels=(lte_label,),
        tags=_provider_tags(proveedor),
        macros=(ZabbixMacro("{$SNMP_COMMUNITY}", community),),
    )


def build_install_plan(
    *,
    tipo: str,
    cliente: str,
    sede: str,
    proveedor: str = "",
    router_ip: str = "",
    is_v7: bool = False,
    localidad: str = "",
    calle: str = "",
    backup_ip: str = "",
    backup_tipo: str = "",
    proveedor_backup: str = "",
    lte_templateid: str = "",
    lte_label: str = "",
    router_username: str = "",
    router_password: str = "",
    snmp_community: str = "",
) -> ZabbixInstallPlan:
    tipo = (tipo or "").strip() or "fibra"
    valid = {t[0] for t in INSTALL_TYPES}
    if tipo not in valid:
        raise ZabbixProfileError(f"Tipo de instalación no válido: {tipo}.")

    hosts: list[ZabbixHostSpec] = []

    if tipo in ("fibra", "fibra_backup"):
        hosts.append(build_router_spec(
            cliente=cliente, sede=sede, proveedor=proveedor, router_ip=router_ip, is_v7=is_v7,
            localidad=localidad, calle=calle, router_username=router_username,
            router_password=router_password, snmp_community=snmp_community,
        ))
        if tipo == "fibra_backup":
            if not backup_tipo:
                raise ZabbixProfileError("Selecciona el tipo de backup (Teltonika, Kite, WAP...).")
            hosts.append(build_backup_spec(
                cliente=cliente, sede=sede, proveedor=proveedor, backup_tipo=backup_tipo,
                backup_ip=backup_ip, localidad=localidad, calle=calle, snmp_community=snmp_community,
            ))

    elif tipo == "chateau":
        provs = tuple(p for p in (proveedor, proveedor_backup) if p)
        hosts.append(build_router_spec(
            cliente=cliente, sede=sede, proveedor=proveedor, router_ip=router_ip, is_v7=is_v7,
            localidad=localidad, calle=calle, router_username=router_username,
            router_password=router_password, snmp_community=snmp_community,
            template_key="FIBRA_CHATEAU", template_label="Mikrotik SNMP FIBRA CHATEAU",
            providers=provs,
        ))

    elif tipo == "dual":
        provs = tuple(p for p in (proveedor, proveedor_backup) if p)
        hosts.append(build_router_spec(
            cliente=cliente, sede=sede, proveedor=proveedor, router_ip=router_ip, is_v7=is_v7,
            localidad=localidad, calle=calle, router_username=router_username,
            router_password=router_password, snmp_community=snmp_community,
            template_key="FIBRA_DUAL", template_label="Mikrotik SNMP FIBRA DUAL",
            providers=provs, name_prefix="DUAL",
        ))

    elif tipo == "lte":
        hosts.append(build_lte_spec(
            cliente=cliente, sede=sede, proveedor=proveedor, lte_templateid=lte_templateid,
            lte_label=lte_label, ip=router_ip, localidad=localidad, calle=calle,
            snmp_community=snmp_community,
        ))

    roles = " + ".join(h.role for h in hosts)
    summary = f"{len(hosts)} host{'s' if len(hosts) > 1 else ''} ({tipo}): {roles}"
    return ZabbixInstallPlan(hosts=tuple(hosts), summary=summary)


def zabbix_questionnaire_defaults() -> dict[str, str]:
    return {
        "tipo": "fibra",
        "provincia": "",
        "cliente": "",
        "sede": "",
        "localidad": "",
        "calle": "",
        "proveedor": "",
        "proveedor_backup": "",
        "router_ip": "",
        "router_password": "",
        "backup_ip": "",
        "backup_tipo": "",
        "lte_templateid": "",
        "snmp_community": default_snmp_community(),
    }
