import unittest

from generator.comms_client import import_products_text, normalize_work_order_payload, parse_work_order_html
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
        self.assertFalse(is_accessory("SIP-T31G"))

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


if __name__ == "__main__":
    unittest.main()
