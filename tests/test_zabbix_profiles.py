from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from generator.zabbix_profiles import (
    ZabbixProfileError,
    build_install_plan,
    resolve_template_id,
)


class ZabbixProfileTests(unittest.TestCase):
    def test_hap_fibra_backup_creates_two_hosts(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ZABBIX_TEMPLATE_ROUTER_AIRE": "100",
                "ZABBIX_TEMPLATE_BACKUP_WAP": "200",
            },
            clear=False,
        ):
            plan = build_install_plan(
                cliente="Cliente",
                sede="Central",
                internet_tipo="FIBRA + BACK UP",
                internet_proveedor="AIRE",
                router_modelo="MikroTik hAP ac2",
                backup_modelo="WAP LTE",
                router_ip="192.168.0.1/24",
                backup_ip="192.168.88.1",
            )
        self.assertEqual(len(plan.hosts), 2)
        self.assertEqual(plan.hosts[0].templateid, "100")
        self.assertEqual(plan.hosts[1].templateid, "200")
        self.assertEqual(plan.hosts[0].ip, "192.168.0.1")
        self.assertEqual(plan.hosts[1].ip, "192.168.88.1")

    def test_chateau_fibra_backup_creates_one_host(self) -> None:
        with patch.dict(
            os.environ,
            {"ZABBIX_TEMPLATE_CHATEAU_FIBRA_BACKUP": "301"},
            clear=False,
        ):
            plan = build_install_plan(
                cliente="Cliente",
                sede="Central",
                internet_tipo="FIBRA + BACK UP",
                internet_proveedor="SARENET",
                router_modelo="CHATEAU",
                backup_modelo="",
                router_ip="10.0.0.1",
            )
        self.assertEqual(len(plan.hosts), 1)
        self.assertEqual(plan.hosts[0].templateid, "301")

    def test_chateau_4g_uses_dedicated_template(self) -> None:
        with patch.dict(os.environ, {"ZABBIX_TEMPLATE_CHATEAU_4G": "401"}, clear=False):
            plan = build_install_plan(
                cliente="Cliente",
                sede="Central",
                internet_tipo="SOLO 4G MONITORIZADO",
                internet_proveedor="",
                router_modelo="CHATEAU",
                backup_modelo="",
                router_ip="10.0.0.5",
            )
        self.assertEqual(len(plan.hosts), 1)
        self.assertEqual(plan.hosts[0].templateid, "401")

    def test_provider_specific_router_template(self) -> None:
        with patch.dict(os.environ, {"ZABBIX_TEMPLATE_ROUTER_ADAMO": "501"}, clear=False):
            template_id, label = resolve_template_id(
                role="router",
                internet_tipo="SOLO FIBRA",
                router_model="MikroTik hAP ac2",
                provider="ADAMO",
                backup_model="",
            )
        self.assertEqual(template_id, "501")
        self.assertIn("ADAMO", label)

    def test_hap_without_backup_raises(self) -> None:
        with patch.dict(os.environ, {"ZABBIX_TEMPLATE_ROUTER_AIRE": "100"}, clear=False):
            with self.assertRaises(ZabbixProfileError):
                build_install_plan(
                    cliente="Cliente",
                    sede="Central",
                    internet_tipo="FIBRA + BACK UP",
                    internet_proveedor="AIRE",
                    router_modelo="MikroTik hAP ac2",
                    backup_modelo="",
                    router_ip="192.168.0.1",
                )


if __name__ == "__main__":
    unittest.main()
