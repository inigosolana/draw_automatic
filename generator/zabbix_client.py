from __future__ import annotations

import json
import os
import unicodedata
import warnings
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ZabbixError(RuntimeError):
    pass


# Provincia GLPI -> provincia usada en los grupos de Zabbix (tras normalizar).
_PROVINCE_ALIASES = {
    "vizcaya": "bizkaia",
    "a coruna": "coruna",
    "guipuzcoa": "gipuzkoa",
}


def _normalize_province(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = " ".join(text.split())
    return _PROVINCE_ALIASES.get(text, text)


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

    def resolve_router_group(self, province: str, role: str) -> dict:
        """Grupo `Routers <role> <Provincia>` (role: Fibra/Backup/LTE).

        Tolera las diferencias reales entre el nombre de provincia en GLPI y el
        sufijo del grupo en Zabbix: acentos (Jaen/Jaén, Leon/León) y nombres
        distintos (Vizcaya→Bizkaia, A Coruña→Coruña).
        """
        target = f"Routers {role} {province}".strip()
        result = self._jsonrpc(
            "hostgroup.get",
            {"output": ["groupid", "name"], "filter": {"name": target}},
        )
        if isinstance(result, list) and result:
            return result[0]

        wanted = _normalize_province(province)
        candidates = self._jsonrpc(
            "hostgroup.get",
            {"output": ["groupid", "name"], "search": {"name": f"Routers {role} "}},
        )
        prefix = f"routers {role} ".casefold()
        for group in candidates if isinstance(candidates, list) else []:
            name = str(group.get("name", "")).strip()
            low = name.casefold()
            if not low.startswith(prefix):
                continue
            suffix = name[len(f"Routers {role} "):]
            if _normalize_province(suffix) == wanted:
                return group
        raise ZabbixError(
            f"No existe el grupo «{target}» en Zabbix (provincia «{province}»). "
            "Revisa la provincia o crea el grupo."
        )

    def list_proxies(self) -> list[dict]:
        result = self._jsonrpc("proxy.get", {"output": ["proxyid", "name"]})
        return result if isinstance(result, list) else []

    def find_host_by_name(self, host: str) -> dict | None:
        result = self._jsonrpc(
            "host.get",
            {"output": ["hostid", "host"], "filter": {"host": host}},
        )
        if isinstance(result, list) and result:
            return result[0]
        return None

    def create_host(
        self,
        *,
        host: str,
        name: str,
        ip: str,
        groupid: str,
        template_ids,
        macros=None,
        tags=None,
        proxyid: str = "",
        monitored_by: str = "1",
        snmp_port: str = "161",
        description: str = "",
        location_lat: str = "",
        location_lon: str = "",
    ) -> dict:
        """Crea un host SNMP v2. `template_ids` es una lista (fibra lleva 2).

        `macros`: iterable de objetos con .macro/.value/.secret (ZabbixMacro).
        `tags`: iterable de tuplas (name, value).
        """
        macro_params = []
        for m in (macros or []):
            entry = {"macro": m.macro, "value": m.value, "type": "1" if m.secret else "0"}
            macro_params.append(entry)

        params = {
            "host": host,
            "name": name or host,
            "groups": [{"groupid": str(groupid)}],
            "interfaces": [
                {
                    "type": 2,  # SNMP
                    "main": 1,
                    "useip": 1,
                    "ip": ip,
                    "dns": "",
                    "port": str(snmp_port),
                    "details": {
                        "version": "2",
                        "community": "{$SNMP_COMMUNITY}",
                        "bulk": "1",
                        "max_repetitions": "10",
                    },
                }
            ],
            "templates": [{"templateid": str(tid)} for tid in template_ids],
            "macros": macro_params,
        }
        if description:
            params["description"] = description
        if str(location_lat).strip() and str(location_lon).strip():
            params["inventory_mode"] = "1"
            params["inventory"] = {"location_lat": str(location_lat), "location_lon": str(location_lon)}
        if tags:
            params["tags"] = [{"tag": t, "value": v} for t, v in tags]
        # Zabbix 7: monitored_by 0 = server, 1 = proxy, 2 = proxy group.
        if proxyid:
            params["monitored_by"] = "1"
            params["proxyid"] = str(proxyid)
        else:
            params["monitored_by"] = "0"
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
