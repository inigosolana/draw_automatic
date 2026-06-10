from pathlib import Path
import tempfile
import unittest

from generator.aliases import resolve_alias
from generator.drawio_writer import build_drawio
from generator.layout_engine import build_layout
from generator.library_loader import load_library
from generator.parser import load_input


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT.parent / "libreria_Ausarta_JUN_2026.xml"
EXAMPLE = ROOT / "examples" / "cliente_demo.json"
TEXT_EXAMPLE = ROOT / "examples" / "cliente_demo.txt"
MULTI_EXAMPLE = ROOT / "examples" / "cliente_multisede.json"


class BasicTests(unittest.TestCase):
    def test_alias_mapping(self) -> None:
        self.assertEqual(resolve_alias("MikroTik hAP ac2"), "Microtik_hAPc")
        self.assertEqual(resolve_alias("Yealink T31P"), "T-31")

    def test_library_load(self) -> None:
        library = load_library(LIBRARY)
        self.assertIsNotNone(library.find("Fanvil V62"))
        self.assertIsNotNone(library.find("MikroTik hAP ac2"))

    def test_multiple_devices_layout(self) -> None:
        data = load_input(EXAMPLE)
        nodes, edges = build_layout(data)
        team_nodes = [node for node in nodes if node.key.startswith("team_")]
        self.assertEqual(len(team_nodes), 6)
        self.assertGreaterEqual(len(edges), 8)

    def test_drawio_xml_generation(self) -> None:
        data = load_input(EXAMPLE)
        library = load_library(LIBRARY)
        nodes, edges = build_layout(data)
        result = build_drawio(nodes, edges, library)
        self.assertIn("<mxfile", result.xml)
        self.assertIn("source=", result.xml)
        self.assertIn("target=", result.xml)

    def test_natural_text_input(self) -> None:
        data = load_input(TEXT_EXAMPLE)
        self.assertEqual(data["cliente"], "Pescados Ginés e Hijos")
        self.assertEqual(data["template"], "con_switch")
        self.assertEqual(len(data["equipos"]), 4)

    def test_multisite_template(self) -> None:
        data = load_input(MULTI_EXAMPLE)
        self.assertEqual(data["template"], "multisede")
        nodes, edges = build_layout(data)
        self.assertTrue(any(node.key == "site_1" for node in nodes))
        self.assertGreaterEqual(len(edges), 3)

    def test_example_can_be_written(self) -> None:
        data = load_input(EXAMPLE)
        library = load_library(LIBRARY)
        nodes, edges = build_layout(data)
        result = build_drawio(nodes, edges, library)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "demo.drawio"
            output.write_text(result.xml, encoding="utf-8")
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
