import unittest
from pathlib import Path

from generator.drawio_reverse import parse_drawio_to_form
from generator.web_adapter import build_drawio_from_data, form_to_data

LIBRARY = str(Path(__file__).resolve().parent / "fixtures" / "test_library.xml")


class DrawioReverseRoundTripTests(unittest.TestCase):
    def _generate(self, form: dict) -> str:
        return build_drawio_from_data(form_to_data(form), LIBRARY).result.xml

    def test_recovers_terminals_with_fields_and_ownership(self) -> None:
        form = {
            "cliente": "ACME SL", "cif": "B123", "sede": "Central", "direccion": "Calle 1",
            "internet_tipo": "FIBRA + BACK UP", "internet_proveedor": "AIRE",
            "internet_velocidad": "1 GB", "ont_modelo": "ONT ZTE",
            "router_modelo": "MikroTik hAP ac2", "backup_modelo": "WAP LTE", "router_ip": "192.168.0.1/24",
            "terminal_details": (
                "T-33 | 3001 | SN123 | AA:BB:CC:DD:EE:FF | 10.0.0.5 | propio | \n"
                "W71H | 3002 | SN9 | 11:22:33:44:55:66 | 10.0.0.6 | ajeno | W60B"
            ),
            "terminal_equipment_text": "1 T-33, extension 3001 propio\n1 W71H, extension 3002 ajeno, base W60B",
        }
        parsed = parse_drawio_to_form(self._generate(form))
        terms = {t["extension"]: t for t in parsed["terminals"]}
        self.assertEqual(len(parsed["terminals"]), 2)
        self.assertEqual(terms["3001"]["model"], "T-33")
        self.assertEqual(terms["3001"]["mac"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(terms["3001"]["ip"], "10.0.0.5")
        self.assertEqual(terms["3001"]["ownership"], "propio")
        self.assertEqual(terms["3002"]["ownership"], "ajeno")  # color rojo -> ajeno

    def test_connectivity_text_has_type_provider_backup(self) -> None:
        form = {
            "cliente": "X", "cif": "", "sede": "S", "direccion": "D",
            "internet_tipo": "FIBRA + BACK UP", "internet_proveedor": "AIRE",
            "internet_velocidad": "1 GB", "ont_modelo": "ONT ZTE",
            "router_modelo": "MikroTik hAP ac2", "backup_modelo": "WAP LTE", "router_ip": "10.0.0.1/24",
        }
        text = parse_drawio_to_form(self._generate(form))["connectivity_text"].upper()
        self.assertIn("FIBRA", text)
        self.assertIn("AIRE", text)
        self.assertIn("WAP LTE", text)

    def test_bad_xml_returns_empty(self) -> None:
        self.assertEqual(parse_drawio_to_form("not xml"), {"terminals": [], "connectivity_text": ""})


if __name__ == "__main__":
    unittest.main()
