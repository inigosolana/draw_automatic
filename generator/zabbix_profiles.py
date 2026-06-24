from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .zabbix_helpers import suggest_zabbix_host_name, suggest_zabbix_visible_name, strip_cidr


class ZabbixProfileError(ValueError):
    pass


INTERNET_TYPES = (
    "FIBRA + BACK UP",
    "SOLO 4G MONITORIZADO",
    "SOLO FIBRA",
)

FIBER_PROVIDERS = (
    "AIRE",
    "ADAMO",
    "MAS MOVIL",
    "EUSKALTEL",
    "SARENET",
    "SARENET ORANGE",
)

ROUTER_MODELS = (
    "MikroTik hAP ac2",
    "MikroTik hAP ac3",
    "CHATEAU",
)

BACKUP_MODELS = (
    "WAP LTE",
    "TELTONIKA",
)


@dataclass(frozen=True)
class ZabbixHostSpec:
    role: str
    host: str
    name: str
    ip: str
    templateid: str
    template_label: str


@dataclass(frozen=True)
class ZabbixInstallPlan:
    hosts: tuple[ZabbixHostSpec, ...]
    summary: str


def _env_template(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def _provider_env_key(provider: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", provider.strip().upper()).strip("_")


def is_hap_router(router_model: str) -> bool:
    return "hap" in router_model.casefold()


def is_chateau_router(router_model: str) -> bool:
    return "chateau" in router_model.casefold()


def resolve_template_id(
    *,
    role: str,
    internet_tipo: str,
    router_model: str,
    provider: str,
    backup_model: str,
) -> tuple[str, str]:
    provider_key = _provider_env_key(provider)
    tipo = internet_tipo.strip().upper()

    if role == "backup":
        backup_key = "TELTONIKA" if backup_model == "TELTONIKA" else "WAP"
        template_id = _env_template(
            f"ZABBIX_TEMPLATE_BACKUP_{backup_key}",
            "ZABBIX_TEMPLATE_BACKUP_WAP",
        )
        label = f"Backup {backup_model or backup_key}"
        if not template_id:
            raise ZabbixProfileError(
                f"Falta la plantilla Zabbix para backup ({backup_model or backup_key})."
            )
        return template_id, label

    if tipo == "SOLO 4G MONITORIZADO":
        template_id = _env_template("ZABBIX_TEMPLATE_CHATEAU_4G")
        if not template_id:
            raise ZabbixProfileError("Falta ZABBIX_TEMPLATE_CHATEAU_4G en el servidor.")
        return template_id, "CHATEAU 4G monitorizado"

    if tipo == "FIBRA + BACK UP" and is_chateau_router(router_model):
        template_id = _env_template(
            f"ZABBIX_TEMPLATE_CHATEAU_FIBRA_{provider_key}",
            "ZABBIX_TEMPLATE_CHATEAU_FIBRA_BACKUP",
        )
        if not template_id:
            raise ZabbixProfileError(
                "Falta la plantilla Zabbix para CHATEAU fibra + backup "
                f"(proveedor {provider or 'sin definir'})."
            )
        return template_id, f"CHATEAU fibra + backup ({provider or 'default'})"

    template_id = _env_template(
        f"ZABBIX_TEMPLATE_ROUTER_{provider_key}",
        "ZABBIX_TEMPLATE_ROUTER_DEFAULT",
        "ZABBIX_DEFAULT_TEMPLATE_ID",
    )
    if not template_id:
        raise ZabbixProfileError(
            f"Falta la plantilla Zabbix para router fibra ({provider or 'sin proveedor'})."
        )
    router_label = "hAP fibra + backup" if tipo == "FIBRA + BACK UP" else "Router fibra"
    return template_id, f"{router_label} ({provider or 'default'})"


def build_install_plan(
    *,
    cliente: str,
    sede: str,
    internet_tipo: str,
    internet_proveedor: str,
    router_modelo: str,
    backup_modelo: str,
    router_ip: str,
    backup_ip: str = "",
) -> ZabbixInstallPlan:
    tipo = internet_tipo.strip().upper()
    router = router_modelo.strip()
    provider = internet_proveedor.strip()
    backup = backup_modelo.strip()
    base_slug = suggest_zabbix_host_name(cliente, sede)
    base_name = suggest_zabbix_visible_name(cliente, sede)
    router_ip_value = strip_cidr(router_ip)
    backup_ip_value = strip_cidr(backup_ip)

    if tipo not in {item.upper() for item in INTERNET_TYPES}:
        raise ZabbixProfileError("Selecciona el tipo de conexion.")
    if not router:
        raise ZabbixProfileError("Selecciona el modelo de router.")
    if not router_ip_value:
        raise ZabbixProfileError("Indica la IP del router.")

    hosts: list[ZabbixHostSpec] = []

    if tipo == "SOLO 4G MONITORIZADO":
        if not is_chateau_router(router):
            router = "CHATEAU"
        template_id, template_label = resolve_template_id(
            role="router",
            internet_tipo=tipo,
            router_model=router,
            provider=provider,
            backup_model=backup,
        )
        hosts.append(
            ZabbixHostSpec(
                role="router",
                host=base_slug,
                name=base_name,
                ip=router_ip_value,
                templateid=template_id,
                template_label=template_label,
            )
        )
        return ZabbixInstallPlan(
            hosts=tuple(hosts),
            summary="1 host CHATEAU (4G monitorizado)",
        )

    if tipo == "SOLO FIBRA":
        if not provider:
            raise ZabbixProfileError("Selecciona el proveedor de fibra.")
        template_id, template_label = resolve_template_id(
            role="router",
            internet_tipo=tipo,
            router_model=router,
            provider=provider,
            backup_model=backup,
        )
        hosts.append(
            ZabbixHostSpec(
                role="router",
                host=base_slug,
                name=base_name,
                ip=router_ip_value,
                templateid=template_id,
                template_label=template_label,
            )
        )
        return ZabbixInstallPlan(
            hosts=tuple(hosts),
            summary=f"1 host router ({provider})",
        )

    if tipo == "FIBRA + BACK UP":
        if not provider:
            raise ZabbixProfileError("Selecciona el proveedor de fibra.")
        if is_chateau_router(router):
            template_id, template_label = resolve_template_id(
                role="router",
                internet_tipo=tipo,
                router_model=router,
                provider=provider,
                backup_model=backup,
            )
            hosts.append(
                ZabbixHostSpec(
                    role="router",
                    host=base_slug,
                    name=base_name,
                    ip=router_ip_value,
                    templateid=template_id,
                    template_label=template_label,
                )
            )
            return ZabbixInstallPlan(
                hosts=tuple(hosts),
                summary=f"1 host CHATEAU fibra + backup integrado ({provider})",
            )

        if is_hap_router(router):
            if backup not in BACKUP_MODELS:
                raise ZabbixProfileError(
                    "Con hAP ac2/ac3 y fibra + backup debes elegir WAP LTE o TELTONIKA."
                )
            if not backup_ip_value:
                raise ZabbixProfileError("Indica la IP del equipo de backup (WAP/Teltonika).")

            router_template_id, router_template_label = resolve_template_id(
                role="router",
                internet_tipo=tipo,
                router_model=router,
                provider=provider,
                backup_model=backup,
            )
            backup_template_id, backup_template_label = resolve_template_id(
                role="backup",
                internet_tipo=tipo,
                router_model=router,
                provider=provider,
                backup_model=backup,
            )
            hosts.extend(
                [
                    ZabbixHostSpec(
                        role="router",
                        host=f"{base_slug}-router",
                        name=f"{base_name} — Router",
                        ip=router_ip_value,
                        templateid=router_template_id,
                        template_label=router_template_label,
                    ),
                    ZabbixHostSpec(
                        role="backup",
                        host=f"{base_slug}-backup",
                        name=f"{base_name} — {backup}",
                        ip=backup_ip_value,
                        templateid=backup_template_id,
                        template_label=backup_template_label,
                    ),
                ]
            )
            return ZabbixInstallPlan(
                hosts=tuple(hosts),
                summary=f"2 hosts: router hAP + {backup} ({provider})",
            )

        raise ZabbixProfileError("Router no valido para fibra + backup.")

    raise ZabbixProfileError("Tipo de conexion no soportado.")


def zabbix_questionnaire_defaults() -> dict[str, str]:
    return {
        "internet_tipo": "",
        "internet_proveedor": "",
        "router_modelo": "",
        "backup_modelo": "",
        "router_ip": "",
        "backup_ip": "",
        "snmp_community": os.environ.get("ZABBIX_DEFAULT_SNMP_COMMUNITY", "").strip(),
        "provincia": "",
        "cliente": "",
        "sede": "",
    }
