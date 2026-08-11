from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("GEOCODE_DISABLED", "1")  # no geocodificar (red) en tests

from app_factory import build_drawio_stores, create_app


class FakeZabbix:
    """Cliente Zabbix simulado que captura las llamadas de create_host."""

    def __init__(self):
        self.created = []
        self.existing = set()  # nombres que ya existen (para probar duplicados)

    def list_proxies(self):
        return [{"proxyid": "10613", "name": "zbxproxy01"}]

    def dominant_proxy(self, groupid):
        return ""

    def find_host_by_name(self, host):
        return {"hostid": "1", "host": host} if host in self.existing else None

    def resolve_router_group(self, province, role):
        gid = {"Fibra": "36", "Backup": "35", "LTE": "37"}.get(role, "36")
        return {"groupid": gid, "name": f"Routers {role} {province}"}

    def create_host(self, **kwargs):
        self.created.append(kwargs)
        return {"hostids": [str(1000 + len(self.created))]}


class ZabbixCreateFlowTests(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {"DRAWIO_RATELIMIT_STORAGE": "memory://"}, clear=False)
        self._env.start()
        self.temp = tempfile.TemporaryDirectory()
        self.stores = build_drawio_stores(Path(self.temp.name))
        self.app = create_app(self.stores)
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, AUTH_REQUIRED=False)
        self.client = self.app.test_client()
        self.fake = FakeZabbix()
        self._p = patch("web.blueprints.zabbix.ZabbixClient.from_environment", return_value=self.fake)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.temp.cleanup()
        self._env.stop()

    def _post(self, **data):
        base = {"provincia": "Cantabria", "cliente": "Cliente Demo", "sede": "Sede 1",
                "snmp_community": "ausarta@conecta"}
        base.update(data)
        return self.client.post("/zabbix", data=base)

    def test_fibra_backup_teltonika_creates_two_correct_hosts(self):
        r = self._post(tipo="fibra_backup", proveedor="SARENET", router_ip="45.13.211.99",
                       router_password="x", routeros_version="v7",
                       backup_tipo="TELTONIKA", backup_ip="172.17.0.30")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.fake.created), 2)
        router, backup = self.fake.created
        self.assertEqual(router["template_ids"], ("10747", "13463"))  # SNMP FIBRA + BGP V7
        self.assertEqual(router["groupid"], "36")  # Fibra
        self.assertIn(("PROVEEDOR", "SARENET"), router["tags"])
        self.assertEqual(backup["template_ids"], ("13483",))  # Teltonika, no SNMP BACKUP
        self.assertEqual(backup["groupid"], "35")  # Backup

    def test_fibra_backup_sin_ip_tunel_crea_solo_fibra_y_avisa(self):
        # Cliente con backup pero sin IP de túnel: se crea la fibra y se avisa,
        # NO se bloquea el alta ni se pierde la fibra.
        r = self._post(tipo="fibra_backup", proveedor="AIRE", router_ip="45.13.211.99",
                       routeros_version="v6", backup_tipo="KITE", backup_ip="")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.fake.created), 1)  # solo la fibra
        self.assertEqual(self.fake.created[0]["template_ids"], ("10747", "11208"))
        self.assertIn("backup", r.get_data(as_text=True).lower())

    def test_password_autofilled_from_passbolt_helper(self):
        with patch("generator.passbolt_credentials.helper_configured", return_value=True), \
             patch("generator.passbolt_credentials.fetch_router_password", return_value="SECRETO-PASSBOLT"):
            r = self._post(tipo="fibra", proveedor="AIRE", router_ip="45.13.211.99",
                           routeros_version="v6")  # sin router_password: debe tirar del helper
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.fake.created), 1)
        macros = {m.macro: m.value for m in self.fake.created[0]["macros"]}
        self.assertEqual(macros.get("{$ROUTEROS_PASSWORD}"), "SECRETO-PASSBOLT")

    def test_lte_flow_no_version_community_only(self):
        r = self._post(tipo="lte", proveedor="MOVISTAR", router_ip="172.18.0.5",
                       lte_templateid="11998")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.fake.created), 1)
        host = self.fake.created[0]
        self.assertEqual(host["template_ids"], ("11998",))
        self.assertEqual(host["groupid"], "37")  # LTE
        self.assertEqual({m.macro for m in host["macros"]}, {"{$SNMP_COMMUNITY}"})

    def test_duplicate_is_skipped(self):
        # Precalcula el nombre y márcalo como existente.
        from generator.zabbix_helpers import build_router_hostname
        name = build_router_hostname("SARENET", "Cliente Demo", "Sede 1")
        self.fake.existing.add(name)
        r = self._post(tipo="fibra", proveedor="SARENET", router_ip="45.13.211.99",
                       router_password="x", routeros_version="v6")
        self.assertEqual(len(self.fake.created), 0)
        self.assertIn("Ya existe", r.get_data(as_text=True))

    def test_missing_ip_shows_error_and_creates_nothing(self):
        r = self._post(tipo="fibra", proveedor="SARENET", router_ip="", routeros_version="v6")
        self.assertEqual(len(self.fake.created), 0)
        self.assertIn("IP", r.get_data(as_text=True))

    def test_version_required_without_helper_or_manual(self):
        r = self._post(tipo="fibra", proveedor="SARENET", router_ip="45.13.211.99",
                       router_password="x")  # sin routeros_version y sin helper
        self.assertEqual(len(self.fake.created), 0)
        self.assertIn("versión", r.get_data(as_text=True).lower())

    def test_from_ot_prefills_fields(self):
        from dataclasses import dataclass, field as dfield

        @dataclass
        class FakeOT:
            work_order_id: str = "9110"
            cliente: str = "COSGUI SL"
            cif: str = ""
            sede: str = "Sede 1"
            direccion: str = "Calle X 1, 39611, El Astillero, Cantabria, Espana"
            internet_tipo: str = "SOLO FIBRA"
            internet_proveedor: str = "AIRE"
            router_modelo: str = "MikroTik hAP ac2"
            backup_modelo: str = ""
            router_ip: str = ""
            warnings: list = dfield(default_factory=list)

        with patch("generator.work_order_import.import_work_order_by_id", return_value=FakeOT()):
            r = self.client.get("/zabbix/api/from-ot?ot=9110")
        self.assertEqual(r.status_code, 200)
        p = r.get_json()
        self.assertEqual(p["tipo"], "fibra")
        self.assertEqual(p["cliente"], "COSGUI SL")
        self.assertEqual(p["proveedor"], "AIRE")
        self.assertEqual(p["provincia"], "Cantabria")

    def test_dual_two_providers_and_prefix(self):
        r = self._post(tipo="dual", proveedor="SARENET", proveedor_backup="ORANGE",
                       router_ip="45.13.211.99", router_password="x", routeros_version="v7")
        self.assertEqual(len(self.fake.created), 1)
        host = self.fake.created[0]
        self.assertEqual(host["template_ids"], ("15558", "13463"))
        prov_tags = [t for t in host["tags"] if t[0] == "PROVEEDOR"]
        self.assertEqual(len(prov_tags), 2)
        # queda registrado quién lo subió, ahora en la Description
        self.assertIn("Subido a Zabbix por", host.get("description", ""))
        self.assertTrue(host["host"].startswith("FTTH_DUAL_"))


if __name__ == "__main__":
    unittest.main()
