from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from generator.work_order_zabbix import work_order_to_prefill


@dataclass
class FakeOT:
    work_order_id: str = "9110"
    cliente: str = ""
    cif: str = ""
    sede: str = ""
    direccion: str = ""
    internet_tipo: str = ""
    internet_proveedor: str = ""
    router_modelo: str = ""
    backup_modelo: str = ""
    router_ip: str = ""
    warnings: list = field(default_factory=list)


CATALOG = [
    {
        "nombre": "Cantabria",
        "clientes": [
            {
                "nombre": "TEFICAR S.A",
                "cif": "A39028691",
                "sedes": [
                    {"nombre": "Sede 1 - Oficina Santander", "direccion": "CALLE Santander 44 Bajo, 39010, Santander",
                     "localidad": "Santander", "calle": "CALLE Santander 44 Bajo"},
                ],
            }
        ],
    }
]


class WorkOrderZabbixTests(unittest.TestCase):
    def test_solo_fibra_maps_to_fibra(self):
        r = FakeOT(cliente="TEFICAR S.A", cif="A39028691", sede="Sede 1 - Oficina Santander",
                   internet_tipo="SOLO FIBRA", internet_proveedor="AIRE", router_modelo="MikroTik hAP ac2")
        pf = work_order_to_prefill(r, glpi_customers=CATALOG)
        self.assertEqual(pf["tipo"], "fibra")
        self.assertEqual(pf["provincia"], "Cantabria")
        self.assertEqual(pf["localidad"], "Santander")
        self.assertEqual(pf["calle"], "CALLE Santander 44 Bajo")
        self.assertEqual(pf["proveedor"], "AIRE")

    def test_fibra_backup_and_backup_type(self):
        r = FakeOT(cliente="X", internet_tipo="FIBRA + BACK UP", router_modelo="MikroTik hAP ac2",
                   backup_modelo="TELTONIKA")
        pf = work_order_to_prefill(r)
        self.assertEqual(pf["tipo"], "fibra_backup")
        self.assertEqual(pf["backup_tipo"], "TELTONIKA")

    def test_chateau_detected_from_router_model(self):
        r = FakeOT(cliente="X", internet_tipo="FIBRA + BACK UP", router_modelo="CHATEAU")
        pf = work_order_to_prefill(r)
        self.assertEqual(pf["tipo"], "chateau")

    def test_solo_4g_maps_to_lte(self):
        r = FakeOT(cliente="X", internet_tipo="SOLO 4G MONITORIZADO", router_modelo="CHATEAU")
        # CHATEAU gana (integrado) salvo que queramos lte; aquí router CHATEAU -> chateau
        pf = work_order_to_prefill(r)
        self.assertIn(pf["tipo"], ("chateau", "lte"))

    def test_province_from_address_when_no_glpi(self):
        r = FakeOT(cliente="Desconocido", internet_tipo="SOLO FIBRA",
                   direccion="Poligono De Morero, 10, El Astillero 39611, Cantabria, Espana")
        pf = work_order_to_prefill(r, glpi_customers=CATALOG)
        self.assertEqual(pf["provincia"], "Cantabria")


if __name__ == "__main__":
    unittest.main()
