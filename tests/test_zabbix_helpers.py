from __future__ import annotations

import unittest

from generator.zabbix_helpers import (
    strip_cidr,
    suggest_zabbix_host_name,
    suggest_zabbix_visible_name,
)


class ZabbixHelperTests(unittest.TestCase):
    def test_strip_cidr(self) -> None:
        self.assertEqual(strip_cidr("192.168.0.1/24"), "192.168.0.1")

    def test_suggest_host_name(self) -> None:
        self.assertEqual(suggest_zabbix_host_name("Cliente S.L.", "Central"), "cliente-s.l.-central")

    def test_suggest_visible_name(self) -> None:
        self.assertEqual(suggest_zabbix_visible_name("Cliente", "Central"), "Cliente - Central")


if __name__ == "__main__":
    unittest.main()
