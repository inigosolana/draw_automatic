from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from generator.zabbix_client import (
    ZabbixClient,
    ZabbixError,
    _normalize_province,
    resolve_zabbix_api_url,
    zabbix_form_defaults,
)


class ZabbixClientTests(unittest.TestCase):
    def test_resolve_api_url_from_base(self) -> None:
        with patch.dict(
            os.environ,
            {"ZABBIX_BASE_URL": "http://zabbix.local:181", "ZABBIX_API_URL": ""},
            clear=False,
        ):
            self.assertEqual(
                resolve_zabbix_api_url(),
                "http://zabbix.local:181/zabbix/api_jsonrpc.php",
            )

    def test_resolve_api_url_explicit(self) -> None:
        with patch.dict(
            os.environ,
            {"ZABBIX_API_URL": "http://custom/api_jsonrpc.php"},
            clear=False,
        ):
            self.assertEqual(resolve_zabbix_api_url(), "http://custom/api_jsonrpc.php")

    def test_from_environment_requires_token(self) -> None:
        with patch.dict(os.environ, {"ZABBIX_BASE_URL": "http://z", "ZABBIX_API_TOKEN": ""}, clear=False):
            self.assertIsNone(ZabbixClient.from_environment())

    def test_create_host_sends_jsonrpc(self) -> None:
        client = ZabbixClient("http://zabbix/api_jsonrpc.php", "token-abc", timeout_ms=5000)
        response_body = json.dumps({"jsonrpc": "2.0", "result": {"hostids": ["10442"]}, "id": 1}).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return response_body

        captured: dict = {}

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return FakeResponse()

        from generator.zabbix_profiles import ZabbixMacro

        with patch("generator.zabbix_client.urlopen", side_effect=fake_urlopen):
            result = client.create_host(
                host="FTTH_SAR_DEMO_SEDE",
                name="FTTH_SAR_DEMO_SEDE",
                ip="45.13.211.99",
                groupid="36",
                template_ids=["10747", "11208"],
                macros=[
                    ZabbixMacro("{$SNMP_COMMUNITY}", "ausarta@conecta"),
                    ZabbixMacro("{$ROUTEROS_USERNAME}", "Ausarta"),
                    ZabbixMacro("{$ROUTEROS_PASSWORD}", "secret"),
                ],
                tags=[("PROVEEDOR", "SARENET")],
                proxyid="10613",
            )

        self.assertEqual(result["hostids"], ["10442"])
        self.assertEqual(captured["headers"]["Authorization"], "Bearer token-abc")
        params = captured["body"]["params"]
        self.assertEqual(params["host"], "FTTH_SAR_DEMO_SEDE")
        self.assertEqual(params["interfaces"][0]["ip"], "45.13.211.99")
        self.assertEqual(len(params["templates"]), 2)
        self.assertEqual(params["tags"], [{"tag": "PROVEEDOR", "value": "SARENET"}])
        # Con proxy: monitored_by=1 (proxy en Zabbix 7) y proxyid presente
        self.assertEqual(params["monitored_by"], "1")
        self.assertEqual(params["proxyid"], "10613")
        macro_names = {item["macro"] for item in params["macros"]}
        self.assertEqual(macro_names, {"{$SNMP_COMMUNITY}", "{$ROUTEROS_USERNAME}", "{$ROUTEROS_PASSWORD}"})

    def test_jsonrpc_error_raises(self) -> None:
        client = ZabbixClient("http://zabbix/api_jsonrpc.php", "token")
        response_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32602, "message": "Invalid params", "data": "Host already exists"},
                "id": 1,
            }
        ).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return response_body

        with patch("generator.zabbix_client.urlopen", return_value=FakeResponse()):
            with self.assertRaises(ZabbixError) as ctx:
                client.create_host(
                    host="x",
                    name="x",
                    ip="1.1.1.1",
                    groupid="1",
                    template_ids=["1"],
                )
        self.assertIn("Host already exists", str(ctx.exception))

    def test_find_host_groups_by_province(self) -> None:
        client = ZabbixClient("http://zabbix/api_jsonrpc.php", "token")
        response_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "result": [{"groupid": "12", "name": "Bizkaia"}],
                "id": 1,
            }
        ).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return response_body

        with patch("generator.zabbix_client.urlopen", return_value=FakeResponse()):
            groups = client.find_host_groups_by_province("Bizkaia")
        self.assertEqual(groups[0]["groupid"], "12")

    def test_normalize_province_aliases_and_accents(self) -> None:
        self.assertEqual(_normalize_province("Vizcaya"), "bizkaia")
        self.assertEqual(_normalize_province("A Coruña"), "coruna")
        self.assertEqual(_normalize_province("Jaen"), _normalize_province("Jaén"))
        self.assertEqual(_normalize_province("Leon"), _normalize_province("León"))
        self.assertEqual(_normalize_province("Cantabria"), "cantabria")

    def test_resolve_router_group_matches_mismatched_province(self) -> None:
        client = ZabbixClient("http://zabbix/api_jsonrpc.php", "token")
        calls = {"n": 0}

        def fake(method, params, request_id=1):
            calls["n"] += 1
            if calls["n"] == 1:  # filtro exacto: no encuentra "Routers Fibra Vizcaya"
                return []
            return [{"groupid": "22", "name": "Routers Fibra Bizkaia"},
                    {"groupid": "36", "name": "Routers Fibra Cantabria"}]

        client._jsonrpc = fake
        group = client.resolve_router_group("Vizcaya", "Fibra")
        self.assertEqual(group["groupid"], "22")

    def test_resolve_host_group_prefers_exact_name(self) -> None:
        client = ZabbixClient("http://zabbix/api_jsonrpc.php", "token")
        client.find_host_groups_by_province = lambda _province: [
            {"groupid": "1", "name": "Hosts Bizkaia"},
            {"groupid": "2", "name": "Bizkaia"},
        ]
        resolved = client.resolve_host_group_for_province("Bizkaia")
        self.assertEqual(resolved["groupid"], "2")

    def test_resolve_host_group_missing_raises(self) -> None:
        client = ZabbixClient("http://zabbix/api_jsonrpc.php", "token")
        client.find_host_groups_by_province = lambda _province: []
        with self.assertRaises(ZabbixError):
            client.resolve_host_group_for_province("Desconocida")

    def test_form_defaults_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ZABBIX_DEFAULT_GROUP_ID": "7",
                "ZABBIX_DEFAULT_TEMPLATE_ID": "99",
                "ZABBIX_ROUTEROS_USERNAME": "ops",
            },
            clear=False,
        ):
            defaults = zabbix_form_defaults()
        self.assertEqual(defaults["groupid"], "7")
        self.assertEqual(defaults["templateid"], "99")
        self.assertEqual(defaults["router_username"], "ops")


if __name__ == "__main__":
    unittest.main()
