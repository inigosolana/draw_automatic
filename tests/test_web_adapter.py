import unittest
from pathlib import Path

from generator.web_adapter import (
    _as_qty,
    _expand_terminal_equipment,
    _parse_router_ip,
    build_drawio_from_box_editor,
    form_to_data,
    form_to_structured_data,
    sanitize_filename,
    structured_to_generator_data,
)

LIBRARY = str(Path(__file__).resolve().parent / "fixtures" / "test_library.xml")


class BoxEditorBuildTests(unittest.TestCase):
    def test_builds_xml_from_boxes_and_links(self) -> None:
        payload = {
            "boxes": [
                {"id": "1", "type": "internet", "model": "", "label": "🌐 FIBRA", "x": 40, "y": 210, "w": 160, "h": 60},
                {"id": "2", "type": "router", "model": "MikroTik hAP ac2", "label": "MikroTik hAP ac2", "x": 300, "y": 210, "w": 120, "h": 120},
                {"id": "3", "type": "terminal", "model": "W71H", "label": "W71H 2001", "x": 540, "y": 80, "w": 120, "h": 80},
            ],
            "links": [{"a": "1", "b": "2"}, {"a": "2", "b": "3"}],
        }
        result = build_drawio_from_box_editor(payload, LIBRARY)
        self.assertIn("<mxfile", result.xml)
        self.assertEqual(result.xml.count('edge="1"'), 2)
        self.assertIn("MikroTik hAP ac2", result.xml)

    def test_includes_header_and_summary_when_data_given(self) -> None:
        payload = {
            "boxes": [
                {"id": "1", "type": "router", "model": "MikroTik hAP ac2", "label": "R", "x": 300, "y": 210, "w": 120, "h": 120},
            ],
            "links": [],
        }
        data = {"cliente": "ACME SL", "cif": "B123", "sede": "Central", "direccion": "Calle Mayor 1", "equipos": []}
        result = build_drawio_from_box_editor(payload, LIBRARY, data)
        self.assertIn("ACME SL", result.xml)
        self.assertIn("Calle Mayor 1", result.xml)
        self.assertIn("Resumen Equipos", result.xml)

    def test_ignores_links_to_missing_boxes(self) -> None:
        payload = {
            "boxes": [{"id": "1", "type": "router", "model": "MikroTik hAP ac2", "label": "R", "x": 0, "y": 0, "w": 120, "h": 120}],
            "links": [{"a": "1", "b": "999"}],
        }
        result = build_drawio_from_box_editor(payload, LIBRARY)
        self.assertEqual(result.xml.count('edge="1"'), 0)

    def test_empty_boxes_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_drawio_from_box_editor({"boxes": []}, LIBRARY)


class AsQtyTests(unittest.TestCase):
    def test_tolerant_of_garbage(self) -> None:
        self.assertEqual(_as_qty(3), 3)
        self.assertEqual(_as_qty("4"), 4)
        self.assertEqual(_as_qty(None), 1)
        self.assertEqual(_as_qty(""), 1)
        self.assertEqual(_as_qty("abc"), 1)
        self.assertEqual(_as_qty(0), 1)
        self.assertEqual(_as_qty(-5), 1)


class SanitizeFilenameTests(unittest.TestCase):
    def test_strips_unsafe_chars_and_keeps_extension(self) -> None:
        name = sanitize_filename("Cliente / S.L.", "Sede #1")
        self.assertTrue(name.endswith(".drawio"))
        self.assertNotIn("/", name)
        self.assertNotIn("#", name)

    def test_empty_falls_back(self) -> None:
        self.assertEqual(sanitize_filename("", ""), "drawio_output.drawio")


class ParseRouterIpTests(unittest.TestCase):
    def test_splits_model_and_ip_on_dash(self) -> None:
        model, ip = _parse_router_ip("hAP ac3 - 192.168.1.1")
        self.assertEqual(model, "hAP ac3")
        self.assertEqual(ip, "192.168.1.1")

    def test_keeps_existing_ip_when_no_dash(self) -> None:
        model, ip = _parse_router_ip("hAP ac3", "10.0.0.1")
        self.assertEqual(model, "hAP ac3")
        self.assertEqual(ip, "10.0.0.1")

    def test_empty_returns_current_ip(self) -> None:
        model, ip = _parse_router_ip("", "10.0.0.1")
        self.assertEqual(model, "")
        self.assertEqual(ip, "10.0.0.1")


class ExpandTerminalEquipmentTests(unittest.TestCase):
    def test_expands_phones_by_quantity_with_extensions(self) -> None:
        equipos = [
            {"tipo": "telefono", "modelo": "T31P", "cantidad": 2, "extensiones": ["101", "102"]},
        ]
        expanded = _expand_terminal_equipment(equipos, details=[])
        self.assertEqual(len(expanded), 2)
        self.assertEqual([item["cantidad"] for item in expanded], [1, 1])
        self.assertEqual([item.get("extension") for item in expanded], ["101", "102"])

    def test_non_terminal_passthrough(self) -> None:
        equipos = [{"tipo": "switch", "modelo": "GS108", "cantidad": 3}]
        expanded = _expand_terminal_equipment(equipos, details=[])
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0]["cantidad"], 3)


class FormRoundTripTests(unittest.TestCase):
    BASE_FORM = {
        "cliente": "Cliente Demo",
        "cif": "B12345678",
        "sede": "Sede Central",
        "direccion": "Calle Mayor, 1",
        "internet_tipo": "FIBRA",
        "internet_velocidad": "600",
        "internet_proveedor": "Telefonica",
        "ont_modelo": "ONT ZTE",
        "router_modelo": "hAP ac3",
        "router_ip": "192.168.1.1",
    }

    def test_structured_then_generator_preserves_core_fields(self) -> None:
        structured = form_to_structured_data(self.BASE_FORM)
        legacy = structured_to_generator_data(structured)
        self.assertEqual(legacy["cliente"], "Cliente Demo")
        self.assertEqual(legacy["sede"], "Sede Central")
        self.assertEqual(legacy["direccion"], "Calle Mayor, 1")
        self.assertEqual(legacy["router"]["modelo"], "hAP ac3")
        self.assertEqual(legacy["internet"]["proveedor"], "Telefonica")

    def test_form_to_data_is_the_two_step_pipeline(self) -> None:
        direct = form_to_data(self.BASE_FORM)
        composed = structured_to_generator_data(form_to_structured_data(self.BASE_FORM))
        self.assertEqual(direct, composed)

    def test_solo_4g_forces_chateau_and_capacity(self) -> None:
        form = dict(self.BASE_FORM)
        form["internet_tipo"] = "SOLO 4G MONITORIZADO"
        form["internet_velocidad"] = "100"
        legacy = form_to_data(form)
        self.assertEqual(legacy["router"]["modelo"], "CHATEAU")
        self.assertEqual(legacy["internet"]["capacidad"], "100")
        self.assertEqual(legacy["internet"]["velocidad"], "")
        self.assertEqual(legacy["ont"]["modelo"], "")


if __name__ == "__main__":
    unittest.main()
