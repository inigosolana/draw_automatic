import unittest

from generator.comms_client import import_products_text, normalize_work_order_payload, parse_work_order_html
from generator.library_loader import load_library
from generator.offer_mapper import (
    extract_work_order_id,
    is_accessory,
    map_offer_to_form,
    normalize_products,
    parse_product_lines,
)


class OfferImportTests(unittest.TestCase):
    def test_extract_work_order_id_from_url(self) -> None:
        self.assertEqual(
            extract_work_order_id("https://comms.aureamotriz.com/customers/work-order/8850"),
            "8850",
        )
        self.assertEqual(extract_work_order_id("8850"), "8850")

    def test_accessory_detection(self) -> None:
        self.assertTrue(is_accessory("Cargador PSU 5V 600mA"))
        self.assertTrue(is_accessory("Ubiquiti POE 48 24W G POE Injector, 48VDC, 24W"))
        self.assertFalse(is_accessory("SIP-T31G"))

    def test_maps_v64_and_ignores_headsets(self) -> None:
        from generator.offer_mapper import is_headset

        self.assertTrue(is_headset("WH63 E2 UC"))
        products = normalize_products(
            [
                {"name": "V64", "quantity": 1, "extension": "3005"},
                {"name": "WH63 E2 UC", "quantity": 1},
                {"name": "Ubiquiti POE 48 24W G POE Injector, 48VDC, 24W", "quantity": 1},
            ]
        )
        result = map_offer_to_form(products)
        self.assertEqual(len(result.terminals), 1)
        self.assertEqual(result.terminals[0]["model"], "FANVIL V64")
        self.assertEqual(result.terminals[0]["extension"], "3005")
        self.assertTrue(any("Cascos/headset ignorado" in w for w in result.warnings))
        self.assertTrue(any("Accesorio ignorado" in w for w in result.warnings))
        self.assertFalse(any("no clasificado" in w for w in result.warnings))

    def test_speed_from_fibra_pro_service_names(self) -> None:
        max_speed = map_offer_to_form(
            normalize_products([{"name": "GPON ONT"}]),
            connectivity_text="Fibra PRO Max Velocidad",
        )
        self.assertEqual(max_speed.internet_velocidad, "1 GB")

        pro_speed = map_offer_to_form(
            normalize_products([{"name": "GPON ONT"}]),
            connectivity_text="Fibra Profesional MásMóvil",
        )
        self.assertEqual(pro_speed.internet_velocidad, "600 MB")

    def test_tl_sg1005d_maps_to_tp_link_5_ports_switch(self) -> None:
        from pathlib import Path

        name = "TL-SG1005D 5-port Gigabit Switch, 5 10/100/1000M RJ45 ports, plastic case"
        result = map_offer_to_form(normalize_products([{"name": name, "quantity": 1}]))
        self.assertEqual(len(result.devices_json), 1)
        self.assertEqual(result.devices_json[0]["tipo"], "switch")
        self.assertEqual(result.devices_json[0]["modelo"], "TP-LINK-5_PORTS")
        self.assertFalse(any("no clasificado" in w for w in result.warnings))

        library = load_library(Path(__file__).resolve().parents[1] / "library" / "libreria_Ausarta_JUN_2026.xml")
        self.assertIsNotNone(library.find("TP-LINK-5_PORTS"))

    def test_gwn7660_maps_to_grandstream_ap(self) -> None:
        from pathlib import Path

        name = "Grandstream GWN7660 Punto de Acceso Wifi 6, 2×2:2 MU-MIM"
        result = map_offer_to_form(normalize_products([{"name": name, "quantity": 1}]))
        self.assertEqual(len(result.devices_json), 1)
        self.assertEqual(result.devices_json[0]["tipo"], "wifi")
        self.assertEqual(result.devices_json[0]["modelo"], "Grandstream AP")
        self.assertFalse(any("no clasificado" in w for w in result.warnings))

        library = load_library(Path(__file__).resolve().parents[1] / "library" / "libreria_Ausarta_JUN_2026.xml")
        self.assertIsNotNone(library.find("Grandstream AP"))

    def test_maps_sample_offer_products(self) -> None:
        products = parse_product_lines(
            "\n".join(
                [
                    "Base DECT W70B",
                    "SIP-T31G",
                    "W71H",
                    "GPON ONT",
                    "CHATEAU 5G AX R17",
                    "Cargador PSU 5V 600mA",
                ]
            )
        )
        result = map_offer_to_form(products, work_order_id="8850")

        self.assertEqual(result.work_order_id, "8850")
        self.assertEqual(result.ont_modelo, "ONT ZTE")
        self.assertEqual(result.router_modelo, "CHATEAU")
        self.assertEqual(result.internet_tipo, "SOLO FIBRA")
        self.assertEqual(len(result.terminals), 2)
        self.assertEqual(result.terminals[0]["model"], "T-31")
        self.assertEqual(result.terminals[1]["model"], "W71H")
        self.assertEqual(result.terminals[1]["dect_base"], "W70B")
        self.assertTrue(any("Cargador" in warning for warning in result.warnings))

    def test_import_products_text_endpoint_helper(self) -> None:
        result = import_products_text("GPON ONT\nCHATEAU 5G AX R17")
        self.assertEqual(result.ont_modelo, "ONT ZTE")
        self.assertEqual(result.router_modelo, "CHATEAU")

    def test_parse_work_order_html_table(self) -> None:
        html = """
        <html><body>
          <strong>Cliente:</strong> Pescados Demo SL
          <strong>CIF:</strong> B12345678
          <table>
            <tr><th>Producto</th><th>Cantidad</th></tr>
            <tr><td>GPON ONT</td><td>1</td></tr>
            <tr><td>SIP-T31G</td><td>1</td></tr>
          </table>
        </body></html>
        """
        parsed = parse_work_order_html(html)
        self.assertEqual(parsed["cliente"], "Pescados Demo SL")
        self.assertEqual(parsed["cif"], "B12345678")
        products = normalize_products(parsed["products"])
        result = map_offer_to_form(products, cliente=parsed["cliente"], cif=parsed["cif"])
        self.assertEqual(result.ont_modelo, "ONT ZTE")
        self.assertEqual(result.terminals[0]["model"], "T-31")

    def test_normalize_work_order_json_payload(self) -> None:
        payload = normalize_work_order_payload(
            {
                "customer": {"name": "Cliente JSON", "tax_id": "A11111111"},
                "site": {"name": "Sede Norte", "address": "Calle 1"},
                "products": [{"name": "W71H", "quantity": 1}, {"name": "Base DECT W70B", "quantity": 1}],
                "connectivity": {"provider": "SARENET", "speed": "600 MB"},
            }
        )
        result = map_offer_to_form(
            normalize_products(payload["products"]),
            cliente=payload["cliente"],
            cif=payload["cif"],
            sede=payload["sede"],
            direccion=payload["direccion"],
            connectivity_text=payload["connectivity_text"],
        )
        self.assertEqual(result.cliente, "Cliente JSON")
        self.assertEqual(result.internet_proveedor, "SARENET")
        self.assertEqual(result.internet_velocidad, "600 MB")
        self.assertEqual(result.terminals[0]["dect_base"], "W70B")

    def test_maps_terminal_extensions_from_product_text(self) -> None:
        products = parse_product_lines("SIP-T31G, extension 2001\nW71H, ext 2002")
        result = map_offer_to_form(products)
        self.assertEqual(len(result.terminals), 2)
        self.assertEqual(result.terminals[0]["extension"], "2001")
        self.assertEqual(result.terminals[1]["extension"], "2002")

    def test_maps_terminal_extensions_from_json_product(self) -> None:
        payload = normalize_work_order_payload(
            {
                "customer": {"name": "Cliente JSON", "tax_id": "A11111111"},
                "site": {"name": "Sede Norte", "address": "Calle 1"},
                "products": [
                    {"name": "SIP-T31G", "quantity": 1, "configuration": "Extensión SIP: 3010"},
                    {"name": "W71H", "quantity": 1, "extension": "3011"},
                ],
            }
        )
        result = map_offer_to_form(normalize_products(payload["products"]))
        self.assertEqual(result.terminals[0]["extension"], "3010")
        self.assertEqual(result.terminals[1]["extension"], "3011")

    def test_masmovil_fiber_backup_tunnel_maps_like_hap_and_wap_lte(self) -> None:
        products = parse_product_lines(
            "\n".join(
                [
                    "Mikrotik wAPR-2Nd&EC200A-EU- Nuevo wAP LTE Kit CPU",
                    "hAP ac2 - RBD52G-5HacD2HnD-TC",
                    "GPON ONT",
                ]
            )
        )
        result = map_offer_to_form(
            products,
            connectivity_text="Servicio: Router Backup Especial 4G Monitorizado Fibra Profesional mas movil",
        )
        self.assertEqual(result.internet_proveedor, "MAS MOVIL")
        self.assertEqual(result.internet_tipo, "FIBRA + BACK UP")
        self.assertEqual(result.router_modelo, "MikroTik hAP ac2")
        self.assertEqual(result.backup_modelo, "WAP LTE")
        self.assertEqual(result.ont_modelo, "ONT ZTE")
        self.assertTrue(any("túnel dedicado" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
