from __future__ import annotations

import unittest

from generator.zabbix_profiles import (
    ZabbixProfileError,
    build_install_plan,
    needs_version,
    template_routeros_bgp,
)


def _plan(**kw):
    base = dict(tipo="fibra", cliente="Cliente", sede="Central", proveedor="AIRE",
                router_ip="1.2.3.4", is_v7=False)
    base.update(kw)
    return build_install_plan(**base)


class ZabbixProfileTests(unittest.TestCase):
    def test_fibra_two_templates_tag_and_macros(self) -> None:
        h = _plan(tipo="fibra", proveedor="SARENET", router_password="secret",
                  localidad="Santander", calle="Calle Castilla 17").hosts[0]
        self.assertEqual(h.host, "FTTH_SAR_CLIENTE_CENTRAL_SANTANDER_CALLE_CASTILLA_17")
        self.assertEqual(h.template_ids, ("10747", "11208"))
        self.assertEqual(h.tags, (("PROVEEDOR", "SARENET"),))
        self.assertEqual({m.macro for m in h.macros},
                         {"{$SNMP_COMMUNITY}", "{$ROUTEROS_USERNAME}", "{$ROUTEROS_PASSWORD}"})

    def test_fibra_v7_uses_bgp_v7(self) -> None:
        h = _plan(tipo="fibra", is_v7=True).hosts[0]
        self.assertEqual(h.template_ids, ("10747", "13463"))
        self.assertEqual(template_routeros_bgp(True)[1], "Template RouterOS BGP V7")

    def test_fibra_backup_mikrotik(self) -> None:
        plan = _plan(tipo="fibra_backup", backup_tipo="KITE", backup_ip="172.17.0.30")
        self.assertEqual(len(plan.hosts), 2)
        b = plan.hosts[1]
        self.assertEqual(b.role, "backup")
        self.assertEqual(b.group_role, "Backup")
        self.assertEqual(b.template_ids, ("10758",))  # Mikrotik SNMP BACKUP
        self.assertEqual({m.macro for m in b.macros}, {"{$SNMP_COMMUNITY}"})

    def test_backup_teltonika_uses_teltonika_template(self) -> None:
        plan = _plan(tipo="fibra_backup", backup_tipo="TELTONIKA", backup_ip="172.17.0.30")
        b = plan.hosts[1]
        self.assertEqual(b.template_ids, ("13483",))  # Teltonika SNMP any device, NO 10758
        self.assertEqual(b.tags, (("PROVEEDOR", "TELTONIKA"),))

    def test_chateau_single_host_two_providers(self) -> None:
        h = _plan(tipo="chateau", is_v7=True, proveedor="AIRE",
                  proveedor_backup="PTV", router_password="x").hosts[0]
        self.assertEqual(h.template_ids, ("14924", "13463"))  # FIBRA CHATEAU + BGP V7
        self.assertEqual(h.tags, (("PROVEEDOR", "AIRE"), ("PROVEEDOR", "PTV")))

    def test_dual_prefix_and_templates(self) -> None:
        h = _plan(tipo="dual", is_v7=True, proveedor="SARENET", proveedor_backup="ORANGE").hosts[0]
        self.assertTrue(h.host.startswith("FTTH_DUAL_"))
        self.assertEqual(h.template_ids, ("15558", "13463"))  # FIBRA DUAL + BGP V7
        self.assertEqual(len(h.tags), 2)

    def test_lte_single_template_community_only(self) -> None:
        h = _plan(tipo="lte", proveedor="MOVISTAR", lte_templateid="11998",
                  lte_label="Mikrotik SNMP LTE 400Gb").hosts[0]
        self.assertEqual(h.group_role, "LTE")
        self.assertEqual(h.template_ids, ("11998",))
        self.assertEqual({m.macro for m in h.macros}, {"{$SNMP_COMMUNITY}"})
        self.assertTrue(h.host.startswith("LTE_MOV_"))

    def test_needs_version(self) -> None:
        self.assertTrue(needs_version("fibra"))
        self.assertTrue(needs_version("chateau"))
        self.assertTrue(needs_version("dual"))
        self.assertFalse(needs_version("lte"))

    def test_missing_ip_raises(self) -> None:
        with self.assertRaises(ZabbixProfileError):
            _plan(tipo="fibra", router_ip="")

    def test_fibra_backup_requires_type(self) -> None:
        with self.assertRaises(ZabbixProfileError):
            _plan(tipo="fibra_backup", backup_ip="172.17.0.30", backup_tipo="")

    def test_invalid_tipo(self) -> None:
        with self.assertRaises(ZabbixProfileError):
            _plan(tipo="satelite")


if __name__ == "__main__":
    unittest.main()
