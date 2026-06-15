from pathlib import Path
import re
import tempfile
import unittest

from generator.aliases import resolve_alias
from generator.drawio_writer import build_drawio
from generator.layout_engine import build_layout, summarize_equipment, validate_input_data
from generator.library_loader import load_library
from generator.parser import load_input, parse_equipment_line


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "tests" / "fixtures" / "test_library.xml"
EXAMPLE = ROOT / "examples" / "cliente_demo.json"
TEXT_EXAMPLE = ROOT / "examples" / "cliente_demo.txt"
MULTI_EXAMPLE = ROOT / "examples" / "cliente_multisede.json"


class BasicTests(unittest.TestCase):
    def test_alias_mapping(self) -> None:
        self.assertEqual(resolve_alias("MikroTik hAP ac2"), "Microtik_hAPc")
        self.assertEqual(resolve_alias("Yealink T31P"), "T-31")
        self.assertEqual(resolve_alias("SIP-T31G"), "T-31")
        self.assertEqual(resolve_alias("Yealink T30P"), "T-30")
        self.assertEqual(resolve_alias("Yealink T43U"), "T-43")
        self.assertEqual(resolve_alias("Yealink T44U"), "T-44")
        self.assertEqual(resolve_alias("Yealink T33G"), "T-33")
        self.assertEqual(resolve_alias("Yealink T73W"), "T-73")
        self.assertEqual(resolve_alias("Fanvil V64"), "FANVIL_V64")
        self.assertEqual(resolve_alias("W70B"), "W60B")
        self.assertEqual(resolve_alias("GPON ONT"), "ONT ZTE")

    def test_library_load(self) -> None:
        library = load_library(LIBRARY)
        self.assertIsNotNone(library.find("Fanvil V62"))
        self.assertEqual(resolve_alias("Fanvil V64"), "FANVIL_V64")
        self.assertEqual(library.find("WAP LTE").title, "Mikrotik LTE6")
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
        self.assertIn('value="ETH1-WAN"', result.xml)
        self.assertIn('y="-14" as="offset"', result.xml)
        self.assertIn("image=data:image/png%3Bbase64,", result.xml)
        self.assertIn("exitX=0.5;exitY=1.0", result.xml)
        ids = re.findall(r'<mxCell id="([^"]+)"', result.xml)
        self.assertEqual(len(ids), len(set(ids)))
        generated_ids = [cell_id for cell_id in ids if cell_id not in {"0", "1"}]
        self.assertTrue(all(re.fullmatch(r"id-[0-9a-f]{12}", cell_id) for cell_id in generated_ids))

    def test_natural_text_input(self) -> None:
        data = load_input(TEXT_EXAMPLE)
        self.assertEqual(data["cliente"], "Pescados Ginés e Hijos")
        self.assertEqual(data["template"], "con_switch")
        self.assertEqual(len(data["equipos"]), 4)

    def test_equipment_without_explicit_quantity_defaults_to_one(self) -> None:
        equipment = parse_equipment_line("Fanvil V62, extension 2001")
        self.assertEqual(equipment["cantidad"], 1)
        self.assertEqual(equipment["extensiones"], ["2001"])
        self.assertEqual(equipment["tipo"], "telefono")

    def test_empty_equipment_line_is_ignored(self) -> None:
        self.assertIsNone(parse_equipment_line("   "))

    def test_invalid_quantity_reports_equipment(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "equipos": [{"tipo": "telefono", "modelo": "Fanvil V62", "cantidad": 0}],
        }
        with self.assertRaisesRegex(ValueError, "Fanvil V62.*entero positivo"):
            build_layout(data)

    def test_extensions_must_be_list_of_strings(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "equipos": [
                {
                    "tipo": "telefono",
                    "modelo": "Fanvil V62",
                    "cantidad": 1,
                    "extensiones": "2001",
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "extensiones.*Fanvil V62.*lista de textos"):
            validate_input_data(data)

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

    def test_xml_escapes_dynamic_text(self) -> None:
        data = {
            "cliente": "A & B <Cliente>",
            "cif": "X&Y",
            "sede": "Sede > Norte",
            "direccion": "Calle <1> & 2",
            "internet": {"tipo": "FTTH & MPLS", "velocidad": "1Gb > 600Mb"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2", "ip": "10.0.0.1/24 & 10.0.0.2"},
            "equipos": [{"tipo": "telefono", "modelo": "Fanvil & V62 <pro>", "cantidad": 1, "extensiones": ["20>01"]}],
        }
        library = load_library(LIBRARY)
        nodes, edges = build_layout(data)
        result = build_drawio(nodes, edges, library)
        self.assertIn("A &amp; B &lt;Cliente&gt;", result.xml)
        self.assertIn("Calle &lt;1&gt; &amp; 2", result.xml)
        self.assertIn("20&gt;01", result.xml)

    def test_validation_warning_for_missing_extensions(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FTTH", "velocidad": "1Gb"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [{"tipo": "telefono", "modelo": "Fanvil V62", "cantidad": 3, "extensiones": ["2001", "2002"]}],
        }
        warnings = validate_input_data(data)
        self.assertEqual(len(warnings), 1)
        self.assertIn("cantidad 3", warnings[0])

    def test_missing_library_icon_warning_is_preserved(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FTTH", "velocidad": "1Gb"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "Router Desconocido"},
            "equipos": [],
        }
        library = load_library(LIBRARY)
        nodes, edges = build_layout(data)
        result = build_drawio(nodes, edges, library)
        self.assertTrue(any("Router Desconocido" in warning for warning in result.warnings))

    def test_page_height_grows_with_many_rows(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FTTH", "velocidad": "1Gb"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [{"tipo": "pc", "modelo": "PC", "cantidad": 10}],
        }
        library = load_library(LIBRARY)
        nodes, edges = build_layout(data)
        result = build_drawio(nodes, edges, library)
        self.assertIn('pageHeight="1370"', result.xml)

    def test_dect_handset_is_placed_below_base_without_router_edge(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FTTH", "velocidad": "1Gb"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [
                {"tipo": "telefono", "modelo": "W70B", "cantidad": 1},
                {"tipo": "telefono", "modelo": "W71H", "cantidad": 1},
            ],
        }
        nodes, edges = build_layout(data)
        base_node = next(node for node in nodes if node.model == "W70B")
        handset_node = next(node for node in nodes if node.model == "W71H")
        self.assertEqual(handset_node.x, base_node.x)
        self.assertGreater(handset_node.y, base_node.y)
        self.assertFalse(any(edge.target == handset_node.key for edge in edges))

    def test_summary_lists_one_equipment_per_line(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FTTH", "velocidad": "1Gb"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "CHATEAU"},
            "equipos": [
                {"tipo": "telefono", "modelo": "W70B", "cantidad": 1},
                {"tipo": "telefono", "modelo": "SIP-T31G", "cantidad": 1},
                {"tipo": "telefono", "modelo": "W71H", "cantidad": 1},
            ],
        }
        summary = summarize_equipment(data)
        self.assertIn("Puestos Voip", summary)
        self.assertIn("Routers/ONT", summary)
        self.assertIn("x1 W60B<br>x1 T-31<br>x1 W71H", summary)
        self.assertIn("CHATEAU<br>ONT ZTE", summary)

    def test_chateau_label_is_short_and_shows_lan(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FTTH", "velocidad": "1Gb"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "S53UG+5HaxD2HaxD-TC&RG650E-EU (CHATEAU 5G AX R17)", "ip": "192.168.0.1/24"},
            "equipos": [],
        }
        nodes, _ = build_layout(data)
        router_node = next(node for node in nodes if node.key == "router")
        self.assertIn("<b>CHATEAU</b>", router_node.label)
        self.assertIn("LAN 192.168.0.1/24", router_node.label)

    def test_phone_label_includes_extension_serial_and_mac(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FTTH", "velocidad": "1Gb"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "CHATEAU", "ip": "192.168.0.1/24"},
            "equipos": [
                {
                    "tipo": "telefono",
                    "modelo": "SIP-T31G",
                    "cantidad": 1,
                    "extensiones": ["2001"],
                    "serial_number": "SN-T31-001",
                    "mac": "AA:BB:CC:DD:EE:03",
                }
            ],
        }
        nodes, _ = build_layout(data)
        phone_node = next(node for node in nodes if node.key.startswith("team_"))
        self.assertIn("EXT 2001", phone_node.label)
        self.assertIn("SN SN-T31-001", phone_node.label)
        self.assertIn("MAC AA:BB:CC:DD:EE:03", phone_node.label)

    def test_hap_backup_uses_eth2_and_phones_start_at_eth3(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FIBRA + BACK UP", "velocidad": "600 MB", "backup": "TELTONIKA"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [{"tipo": "telefono", "modelo": "T-31", "cantidad": 2}],
        }
        nodes, edges = build_layout(data)
        self.assertTrue(any(node.key == "backup" and node.model == "TELTONIKA" for node in nodes))
        self.assertTrue(any(edge.target == "backup" and edge.label == "ETH2-BACKUP" for edge in edges))
        phone_labels = [edge.label for edge in edges if edge.target.startswith("team_")]
        self.assertEqual(phone_labels, ["ETH3-LAN", "ETH4-LAN"])

    def test_chateau_backup_is_integrated(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FIBRA + BACK UP", "velocidad": "600 MB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "CHATEAU"},
            "equipos": [],
        }
        nodes, edges = build_layout(data)
        router = next(node for node in nodes if node.key == "router")
        self.assertIn("BACKUP 4G INTEGRADO", router.label)
        self.assertFalse(any(node.key == "backup" for node in nodes))
        self.assertFalse(any(edge.label == "ETH2-BACKUP" for edge in edges))

    def test_switch_uses_eth3_and_phones_use_switch_ports(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "SOLO FIBRA", "velocidad": "600 MB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-Link 16P", "cantidad": 1},
                {"tipo": "telefono", "modelo": "T-31", "cantidad": 2},
            ],
        }
        _, edges = build_layout(data)
        self.assertTrue(any(edge.target == "switch" and edge.label == "ETH3-LAN" for edge in edges))
        phone_edges = [edge for edge in edges if edge.target.startswith("team_")]
        self.assertEqual([edge.source for edge in phone_edges], ["switch", "switch"])
        self.assertEqual([edge.label for edge in phone_edges], ["SW1-ETH", "SW2-ETH"])

    def test_summary_table_does_not_overlap_switch(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "SOLO FIBRA", "velocidad": "600 MB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-Link 16P", "cantidad": 1},
                {"tipo": "telefono", "modelo": "T-44", "cantidad": 1},
            ],
        }
        nodes, _ = build_layout(data)
        switch = next(node for node in nodes if node.key == "switch")
        summary = next(node for node in nodes if node.key == "summary")
        switch_box = (switch.x, switch.y, switch.x + switch.width, switch.y + switch.height)
        summary_box = (summary.x, summary.y, summary.x + summary.width, summary.y + summary.height)
        overlaps = not (
            switch_box[2] <= summary_box[0]
            or summary_box[2] <= switch_box[0]
            or switch_box[3] <= summary_box[1]
            or summary_box[3] <= switch_box[1]
        )
        self.assertFalse(overlaps)
        self.assertGreater(summary.y, switch.y + switch.height - 20)


if __name__ == "__main__":
    unittest.main()
