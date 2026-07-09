from __future__ import annotations

import json
import os
import warnings
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ZabbixError(RuntimeError):
    pass


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def resolve_zabbix_api_url() -> str:
    explicit = os.environ.get("ZABBIX_API_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    base = os.environ.get("ZABBIX_BASE_URL", "").strip().rstrip("/")
    if not base:
        return ""
    path = os.environ.get("ZABBIX_API_PATH", "/zabbix/api_jsonrpc.php").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


class ZabbixClient:
    def __init__(self, api_url: str, api_token: str, *, timeout_ms: int = 7000) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_token = api_token.strip()
        self.timeout = max(timeout_ms, 1000) / 1000.0
        allow_insecure = os.environ.get("ZABBIX_ALLOW_INSECURE", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if (
            self.api_url
            and not self.api_url.lower().startswith("https://")
            and not allow_insecure
        ):
            warnings.warn(
                "ZABBIX_API_URL no usa HTTPS: el token Bearer viajara sin cifrar. "
                "Usa https:// o define ZABBIX_ALLOW_INSECURE=1 para silenciar este aviso.",
                stacklevel=2,
            )

    @classmethod
    def from_environment(cls) -> ZabbixClient | None:
        api_url = resolve_zabbix_api_url()
        api_token = os.environ.get("ZABBIX_API_TOKEN", "").strip()
        if not api_url or not api_token:
            return None
        timeout_ms = _env_int("ZABBIX_HTTP_TIMEOUT_MS", 7000)
        return cls(api_url, api_token, timeout_ms=timeout_ms)

    def _jsonrpc(self, method: str, params: dict, request_id: int = 1) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id,
        }
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.api_url,
            data=body,
            headers={
                "Content-Type": "application/json-rpc",
                "Authorization": f"Bearer {self.api_token}",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ZabbixError(f"Zabbix HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ZabbixError(f"No se pudo conectar con Zabbix: {exc.reason}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ZabbixError("Respuesta invalida de Zabbix.") from exc

        if "error" in data:
            error = data["error"]
            if isinstance(error, dict):
                message = error.get("data", error.get("message", "Error desconocido"))
            else:
                message = error
            raise ZabbixError(str(message))
        return data.get("result", {})

    def find_host_groups_by_province(self, province: str) -> list[dict]:
        query = province.strip()
        if not query:
            return []
        result = self._jsonrpc(
            "hostgroup.get",
            {
                "output": ["groupid", "name"],
                "search": {"name": query},
                "searchByAny": True,
            },
        )
        return result if isinstance(result, list) else []

    def resolve_host_group_for_province(self, province: str) -> dict:
        groups = self.find_host_groups_by_province(province)
        if not groups:
            raise ZabbixError(
                f"No se encontro ningun grupo en Zabbix para la provincia «{province}»."
            )
        normalized = province.strip().casefold()
        for group in groups:
            if str(group.get("name", "")).strip().casefold() == normalized:
                return group
        for group in groups:
            name = str(group.get("name", "")).strip().casefold()
            if name and (normalized in name or name in normalized):
                return group
        return groups[0]

    def create_host(
        self,
        *,
        host: str,
        name: str,
        ip: str,
        groupid: str,
        proxyid: str,
        snmp_community: str,
        templateid: str,
        monitored_by: str,
        router_username: str = "",
        router_password: str = "",
    ) -> dict:
        macros = [
            {"macro": "{$SNMP_COMMUNITY}", "value": snmp_community},
        ]
        if router_username:
            macros.append({"macro": "{$ROUTEROS_USERNAME}", "value": router_username})
        if router_password:
            macros.append({"macro": "{$ROUTEROS_PASSWORD}", "value": router_password})

        params = {
            "host": host,
            "name": name,
            "groups": [{"groupid": str(groupid)}],
            "monitored_by": str(monitored_by),
            "proxyid": str(proxyid),
            "interfaces": [
                {
                    "type": 2,
                    "main": 1,
                    "useip": 1,
                    "ip": ip,
                    "dns": "",
                    "port": "161",
                    "details": {
                        "version": "2",
                        "community": "{$SNMP_COMMUNITY}",
                        "bulk": "1",
                        "max_repetitions": "10",
                    },
                }
            ],
            "templates": [{"templateid": str(templateid)}],
            "macros": macros,
        }
        return self._jsonrpc("host.create", params)


def zabbix_form_defaults() -> dict[str, str]:
    return {
        "groupid": os.environ.get("ZABBIX_DEFAULT_GROUP_ID", "").strip(),
        "proxyid": os.environ.get("ZABBIX_DEFAULT_PROXY_ID", "").strip(),
        "templateid": os.environ.get("ZABBIX_DEFAULT_TEMPLATE_ID", "").strip(),
        "monitored_by": os.environ.get("ZABBIX_DEFAULT_MONITORED_BY", "1").strip(),
        "router_username": os.environ.get("ZABBIX_ROUTEROS_USERNAME", "").strip(),
        "router_password": os.environ.get("ZABBIX_ROUTEROS_PASSWORD", "").strip(),
    }
