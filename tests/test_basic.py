from pathlib import Path
import re
import tempfile
import unittest

from generator.aliases import resolve_alias
from generator.drawio_writer import build_drawio
from generator.geometry import PAGE_RIGHT
from generator.layout_engine import SUMMARY_X, _anchor_exit_x, _canvas_bounds, build_layout, summarize_equipment, validate_input_data
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
        self.assertEqual(resolve_alias("MikroTik hAP ac3"), "MikroTik hAP ac3")
        self.assertEqual(resolve_alias("Yealink T31P"), "T-31")
        self.assertEqual(resolve_alias("SIP-T31G"), "T-31")
        self.assertEqual(resolve_alias("Yealink T30P"), "T-30")
        self.assertEqual(resolve_alias("Yealink T43U"), "T-43")
        self.assertEqual(resolve_alias("Yealink T44U"), "T-44")
        self.assertEqual(resolve_alias("Yealink T33G"), "T-33")
        self.assertEqual(resolve_alias("Yealink T73W"), "T-73")
        self.assertEqual(resolve_alias("Fanvil V64"), "FANVIL_V64")
        self.assertEqual(resolve_alias("V64"), "FANVIL V64")
        self.assertEqual(resolve_alias("FANVIL X303G"), "FANVIL_X303G")
        self.assertEqual(resolve_alias("x303g"), "FANVIL_X303G")
        self.assertEqual(resolve_alias("TP-Link TL-SG108"), "TP-Link 8P")
        self.assertEqual(resolve_alias("TL-SG1005D"), "TP-LINK-5_PORTS")
        self.assertEqual(resolve_alias("switch TP-LINK-5_PORTS"), "TP-LINK-5_PORTS")
        self.assertEqual(resolve_alias("W70B"), "W70B")
        self.assertEqual(resolve_alias("GPON ONT"), "ONT ZTE")

    def test_library_load(self) -> None:
        library = load_library(LIBRARY)
        self.assertIsNotNone(library.find("Fanvil V62"))
        self.assertEqual(resolve_alias("Fanvil V64"), "FANVIL_V64")
        self.assertEqual(library.find("WAP LTE").title, "Mikrotik wAP LTE")
        self.assertIsNotNone(library.find("MikroTik hAP ac2"))

    def test_library_resolves_switch_prefixed_tp_link_5_ports(self) -> None:
        real_library = ROOT / "library" / "libreria_Ausarta_JUN_2026.xml"
        if not real_library.is_file():
            self.skipTest("libreria real no disponible en este entorno")
        library = load_library(real_library)
        self.assertIsNotNone(library.find("switch TP-LINK-5_PORTS"))
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "SOLO FIBRA", "velocidad": "600 MB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [
                {"tipo": "switch", "modelo": "switch TP-LINK-5_PORTS", "cantidad": 1},
                {"tipo": "switch", "modelo": "switch TP-LINK-5_PORTS", "cantidad": 1},
                {"tipo": "wifi", "modelo": "Grandstream AP", "cantidad": 1},
            ],
        }
        nodes, edges = build_layout(data)
        result = build_drawio(nodes, edges, library)
        self.assertNotIn("No se ha encontrado icono para: switch TP-LINK-5_PORTS", result.warnings)

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
        self.assertIn("image=data:image/png%3Bbase64,", result.xml)
        self.assertIn("exitY=1.0", result.xml)
        self.assertIn("ETH1", result.xml)
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

    def test_equipment_line_parses_dect_base(self) -> None:
        equipment = parse_equipment_line("1 W71H, extension 3003, base W80B propio")
        self.assertEqual(equipment["modelo"], "W71H")
        self.assertEqual(equipment["dect_base"], "W80B")
        self.assertEqual(equipment["extensiones"], ["3003"])

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
        page_height = int(re.search(r'pageHeight="(\d+)"', result.xml).group(1))
        self.assertGreaterEqual(page_height, 827)

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
        self.assertFalse(any(edge.target == handset_node.key and edge.label and edge.label.endswith("-ETH") for edge in edges))
        self.assertTrue(any(edge.target == handset_node.key and edge.label == "DECT" for edge in edges))

    def test_dect_handset_without_base_gets_auto_base_with_ethernet(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "SOLO FIBRA", "velocidad": "600 MB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "CHATEAU"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-Link 8P", "cantidad": 1},
                {"tipo": "telefono", "modelo": "W71H", "cantidad": 1, "extensiones": ["3200"]},
            ],
        }
        nodes, edges = build_layout(data)
        base_node = next(node for node in nodes if node.meta and node.meta.get("dect_role") == "base")
        handset_node = next(node for node in nodes if node.model == "W71H")
        self.assertEqual(base_node.model, "W60B")
        self.assertEqual(handset_node.x, base_node.x)
        self.assertGreater(handset_node.y, base_node.y)
        self.assertTrue(any(edge.target == base_node.key and edge.source == "switch" for edge in edges))
        self.assertIn("ETH1", base_node.label)
        self.assertFalse(any(edge.target == handset_node.key and edge.label and edge.label.endswith("-ETH") for edge in edges))
        self.assertTrue(any(edge.target == handset_node.key and edge.label == "DECT" for edge in edges))

    def test_dect_handset_uses_selected_base_model(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "SOLO FIBRA", "velocidad": "600 MB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "CHATEAU"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-Link 8P", "cantidad": 1},
                {
                    "tipo": "terminal_dect",
                    "modelo": "W71H",
                    "cantidad": 1,
                    "extension": "3003",
                    "dect_base": "W70B",
                },
            ],
        }
        nodes, _ = build_layout(data)
        base_node = next(node for node in nodes if node.meta and node.meta.get("dect_role") == "base")
        self.assertEqual(base_node.model, "W70B")
        self.assertIn("ETH1", base_node.label)

    def test_multiple_dect_handsets_share_one_base(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "SOLO FIBRA", "velocidad": "600 MB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "CHATEAU"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-Link 8P", "cantidad": 1},
                {"tipo": "telefono", "modelo": "W71H", "cantidad": 1, "extension": "3001", "dect_base": "W70B"},
                {"tipo": "telefono", "modelo": "W71H", "cantidad": 1, "extension": "3002", "dect_base": "W70B"},
                {"tipo": "telefono", "modelo": "W73H", "cantidad": 1, "extension": "3003", "dect_base": "W70B"},
            ],
        }
        nodes, edges = build_layout(data)
        bases = [node for node in nodes if node.meta and node.meta.get("dect_role") == "base"]
        handsets = sorted(
            (node for node in nodes if node.meta and node.meta.get("dect_role") == "handset"),
            key=lambda node: node.y,
        )
        self.assertEqual(len(bases), 1)
        self.assertEqual(bases[0].model, "W70B")
        self.assertEqual(len(handsets), 3)
        self.assertEqual(handsets[0].y, handsets[1].y)
        self.assertEqual(handsets[1].y, handsets[2].y)
        handset_xs = sorted(handset.x for handset in handsets)
        self.assertLess(handset_xs[0], bases[0].x)
        self.assertGreater(handset_xs[-1], bases[0].x)
        self.assertEqual(len([edge for edge in edges if edge.label == "DECT"]), 3)
        self.assertEqual(len([edge for edge in edges if edge.target == bases[0].key and edge.source == "switch"]), 1)

    def test_dense_phone_row_avoids_dect_handset_overlap(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "SOLO FIBRA", "velocidad": "1 GB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "CHATEAU", "ip": "192.168.0.1/24"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-LINK-5_PORTS", "cantidad": 1},
                *[{"tipo": "telefono", "modelo": "T-33", "cantidad": 1} for _ in range(8)],
                {"tipo": "telefono", "modelo": "W71H", "cantidad": 1, "extension": "3001", "dect_base": "W70B"},
                {"tipo": "telefono", "modelo": "W71H", "cantidad": 1, "extension": "3002", "dect_base": "W70B"},
            ],
        }
        nodes, _ = build_layout(data)
        devices = [
            node
            for node in nodes
            if node.key.startswith("team_") or node.key in {"router", "switch", "ont"}
        ]
        for index, a in enumerate(devices):
            for b in devices[index + 1 :]:
                overlaps = (
                    a.x < b.x + b.width
                    and a.x + a.width > b.x
                    and a.y < b.y + b.height
                    and a.y + a.height > b.y
                )
                self.assertFalse(overlaps, f"{a.key} overlaps {b.key}")

    def test_w70b_equipment_before_handsets_reuses_same_base(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "SOLO FIBRA", "velocidad": "600 MB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [
                {"tipo": "telefono", "modelo": "W70B", "cantidad": 1},
                {"tipo": "telefono", "modelo": "W53H", "cantidad": 1, "extension": "3010", "dect_base": "W70B"},
                {"tipo": "telefono", "modelo": "W53H", "cantidad": 1, "extension": "3011", "dect_base": "W70B"},
            ],
        }
        nodes, edges = build_layout(data)
        bases = [node for node in nodes if node.meta and node.meta.get("dect_role") == "base"]
        handsets = [node for node in nodes if node.meta and node.meta.get("dect_role") == "handset"]
        self.assertEqual(len(bases), 1)
        self.assertEqual(len(handsets), 2)
        self.assertFalse(any(edge.target == handsets[0].key and edge.label and edge.label.endswith("-LAN") for edge in edges))

    def test_switch_port_is_shown_on_device_label(self) -> None:
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
                {"tipo": "telefono", "modelo": "T-33", "cantidad": 1, "extensiones": ["3002"]},
            ],
        }
        nodes, _ = build_layout(data)
        phone_node = next(node for node in nodes if node.model == "T-33")
        self.assertIn("ETH1", phone_node.label)
        self.assertIn("T-33", phone_node.label)

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
        self.assertIn("Switches/Otros", summary)
        self.assertIn("x1 W70B<br>x1 T-31<br>x1 W71H", summary)
        self.assertIn("CHATEAU<br>ONT ZTE", summary)

    def test_summary_includes_switch_and_other_devices(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FIBRA + BACK UP", "velocidad": "1 GB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "CHATEAU"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-Link 8P", "cantidad": 1},
                {"tipo": "wifi", "modelo": "Grandstream AP", "cantidad": 1},
                {"tipo": "telefono", "modelo": "T-33", "cantidad": 4},
            ],
        }
        summary = summarize_equipment(data)
        self.assertIn("x1 TP-Link 8P", summary)
        self.assertIn("x1 Grandstream AP", summary)
        self.assertIn("x4 T-33", summary)
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

    def test_switch_is_below_router_and_backup_is_to_the_right(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "FIBRA + BACK UP", "velocidad": "600 MB", "backup": "WAP LTE"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-Link 16P", "cantidad": 1},
                {"tipo": "telefono", "modelo": "T-33", "cantidad": 1},
            ],
        }
        nodes, edges = build_layout(data)
        router = next(node for node in nodes if node.key == "router")
        switch = next(node for node in nodes if node.key == "switch")
        backup = next(node for node in nodes if node.key == "backup")
        self.assertGreater(switch.y, router.y + router.height)
        self.assertAlmostEqual(switch.x + switch.width / 2, router.x + router.width / 2, delta=20)
        self.assertGreater(backup.x, router.x + router.width)
        self.assertLess(abs((backup.y + backup.height / 2) - (router.y + router.height / 2)), 40)
        self.assertTrue(any(edge.label == "ETH3-LAN" and edge.target == "switch" for edge in edges))
        self.assertTrue(any(edge.label == "ETH2-BACKUP" and edge.target == "backup" for edge in edges))

    def test_summary_includes_backup_in_routers_column(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "internet": {"tipo": "FIBRA + BACK UP", "velocidad": "600 MB", "backup": "WAP LTE"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [{"tipo": "telefono", "modelo": "T-33", "cantidad": 4}],
        }
        summary = summarize_equipment(data)
        self.assertIn("Microtik_hAPc<br>ONT ZTE<br>Mikrotik wAP LTE", summary)

    def test_switch_devices_use_vertical_columns_without_shared_bus(self) -> None:
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
                {"tipo": "wifi", "modelo": "Grandstream AP", "cantidad": 1},
                {"tipo": "telefono", "modelo": "T-30", "cantidad": 1, "extensiones": ["3002"]},
                {"tipo": "telefono", "modelo": "T-73", "cantidad": 1, "extensiones": ["3010"]},
            ],
        }
        nodes, edges = build_layout(data)
        switch = next(node for node in nodes if node.key == "switch")
        devices = sorted(
            (node for node in nodes if node.key.startswith("team_")),
            key=lambda node: node.x,
        )
        self.assertEqual(len(devices), 3)
        for index, device in enumerate(devices, start=1):
            self.assertIn(f"ETH{index}", device.label)
            self.assertGreaterEqual(device.x + device.width, device.x)
            self.assertLess(device.x, SUMMARY_X - 40)
        for edge in edges:
            if edge.source != "switch" or not edge.target.startswith("team_"):
                continue
            self.assertTrue(edge.label and edge.label.startswith("ETH"))
            self.assertIsNotNone(edge.waypoints)
            self.assertGreaterEqual(len(edge.waypoints), 1)
        row_center = devices[1].x + devices[1].width / 2
        switch_center = switch.x + switch.width / 2
        self.assertAlmostEqual(row_center, switch_center, delta=80)

    def test_phones_bypass_switch_when_switch_telefonia_disabled(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "switch_telefonia": False,
            "internet": {"tipo": "SOLO FIBRA", "velocidad": "600 MB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-Link 16P", "cantidad": 1},
                {"tipo": "telefono", "modelo": "T-31", "cantidad": 1, "extensiones": ["2001"]},
                {"tipo": "pc", "modelo": "PC Oficina", "cantidad": 1},
            ],
        }
        nodes, edges = build_layout(data)
        phone = next(node for node in nodes if node.key.startswith("team_") and "T-31" in node.label)
        pc = next(node for node in nodes if node.key.startswith("team_") and "PC Oficina" in node.label)
        phone_edge = next(edge for edge in edges if edge.target == phone.key)
        pc_edge = next(edge for edge in edges if edge.target == pc.key)
        self.assertEqual(phone_edge.source, "router")
        self.assertIn("ETH4", phone.label)
        self.assertEqual(phone_edge.label, "ETH4-LAN")
        self.assertEqual(pc_edge.source, "switch")
        self.assertIn("ETH1", pc.label)

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
        nodes, edges = build_layout(data)
        self.assertTrue(any(edge.target == "switch" and edge.label == "ETH3-LAN" for edge in edges))
        phone_edges = [edge for edge in edges if edge.target.startswith("team_")]
        self.assertEqual([edge.source for edge in phone_edges], ["switch", "switch"])
        phones = sorted(
            (node for node in nodes if node.key.startswith("team_")),
            key=lambda node: node.x,
        )
        self.assertIn("ETH1", phones[0].label)
        self.assertIn("ETH2", phones[1].label)

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
        self.assertGreaterEqual(summary.x, switch.x + switch.width)
        self.assertLess(summary.y + summary.height, 400)

    def test_switch_phones_are_aligned_in_row_with_matching_exit_ports(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "SOLO FIBRA", "velocidad": "600 MB"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "CHATEAU"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-Link 8P", "cantidad": 1},
                {"tipo": "telefono", "modelo": "T-33", "cantidad": 1},
                {"tipo": "telefono", "modelo": "T-44", "cantidad": 1},
                {"tipo": "telefono", "modelo": "T-73", "cantidad": 1},
                {"tipo": "telefono", "modelo": "W71H", "cantidad": 1},
            ],
        }
        nodes, edges = build_layout(data)
        switch = next(node for node in nodes if node.key == "switch")
        phones = sorted(
            (node for node in nodes if node.key.startswith("team_") and node.meta and node.meta.get("dect_role") != "handset"),
            key=lambda node: node.x,
        )
        self.assertEqual(len(phones), 4)
        self.assertLessEqual(len({node.y for node in phones}), 2)
        self.assertGreater(phones[0].y, switch.y + switch.height)
        # Las filas de teléfonos se reparten a lo ancho de toda la página (van
        # muy por debajo de la tabla resumen), así que el límite es PAGE_RIGHT.
        for phone in phones:
            self.assertLessEqual(phone.x + phone.width, PAGE_RIGHT + 10)
        phone_edges = [edge for edge in edges if edge.source == "switch" and edge.target.startswith("team_")]
        self.assertEqual(len(phone_edges), 4)
        for edge in phone_edges:
            self.assertTrue(edge.label and edge.label.startswith("ETH"))
            self.assertIsNotNone(edge.waypoints)
        # Cada cable sale de un punto PROPIO y distinto del switch (repartidos a lo
        # ancho del borde inferior, en 0..1): ninguna línea sale de otra.
        exits = [edge.exit_x for edge in phone_edges]
        self.assertEqual(len(set(round(x, 3) for x in exits)), len(exits))
        for x in exits:
            self.assertGreater(x, 0.0)
            self.assertLess(x, 1.0)

    def test_adamo_ont_uses_normal_icon_with_red_name(self) -> None:
        data = {
            "cliente": "Demo",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "FIBRA + BACK UP", "velocidad": "300 MB", "proveedor": "ADAMO"},
            "ont": {"modelo": "ONT ADAMO"},
            "router": {"modelo": "MikroTik hAP ac2"},
            "equipos": [{"tipo": "telefono", "modelo": "T-33", "cantidad": 1, "extensiones": ["3001"]}],
        }
        nodes, _ = build_layout(data)
        ont = next(n for n in nodes if n.key == "ont")
        # Icono de ONT normal (generico), no la caja vacia de "ONT ADAMO".
        self.assertEqual(ont.icon_model, "ONT")
        # Nombre en rojo porque el equipo es del proveedor (ADAMO).
        self.assertIn("#d00000", ont.label)

    def test_dual_switches_route_telephony_and_data_separately(self) -> None:
        data = {
            "cliente": "INMOBILIARIA HUMEDO SL",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "FIBRA + BACK UP", "velocidad": "1 GB", "proveedor": "AIRE"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2", "ip": "192.168.0.1/24"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-LINK-5_PORTS", "cantidad": 1},
                {"tipo": "switch", "modelo": "TP-LINK-5_PORTS", "cantidad": 1},
                {"tipo": "telefono", "modelo": "FANVIL V64", "cantidad": 1, "extensiones": ["3001"]},
                {"tipo": "telefono", "modelo": "FANVIL V64", "cantidad": 1, "extensiones": ["3002"]},
                {"tipo": "wifi", "modelo": "Grandstream AP", "cantidad": 1},
            ],
        }
        nodes, edges = build_layout(data)
        switches = [node for node in nodes if node.key in {"switch", "switch_datos"}]
        self.assertEqual(len(switches), 2)
        self.assertTrue(any(edge.label == "ETH3-LAN" and edge.target == "switch" for edge in edges))
        self.assertTrue(any(edge.label == "ETH4-LAN" and edge.target == "switch_datos" for edge in edges))
        phones = sorted(
            (node for node in nodes if node.key.startswith("team_") and "FANVIL" in node.label),
            key=lambda node: node.x,
        )
        ap = next(node for node in nodes if node.key.startswith("team_") and "Grandstream" in node.label)
        self.assertEqual(len(phones), 2)
        for phone in phones:
            phone_edge = next(edge for edge in edges if edge.target == phone.key)
            self.assertEqual(phone_edge.source, "switch")
        ap_edge = next(edge for edge in edges if edge.target == ap.key)
        self.assertEqual(ap_edge.source, "switch_datos")

    def test_dual_switch_cables_use_separate_bus_lanes(self) -> None:
        data = {
            "cliente": "INMOBILIARIA HUMEDO SL",
            "sede": "Central",
            "direccion": "Bilbao",
            "template": "con_switch",
            "internet": {"tipo": "FIBRA + BACK UP", "velocidad": "1 GB", "proveedor": "AIRE"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "MikroTik hAP ac2", "ip": "192.168.0.1/24"},
            "equipos": [
                {"tipo": "switch", "modelo": "TP-LINK-5_PORTS", "cantidad": 1},
                {"tipo": "switch", "modelo": "TP-LINK-5_PORTS", "cantidad": 1},
                {"tipo": "telefono", "modelo": "FANVIL V64", "cantidad": 1, "extensiones": ["3001"]},
                {"tipo": "telefono", "modelo": "FANVIL V64", "cantidad": 1, "extensiones": ["3002"]},
                {"tipo": "telefono", "modelo": "FANVIL V64", "cantidad": 1, "extensiones": ["3000"]},
                {"tipo": "wifi", "modelo": "Grandstream AP", "cantidad": 1},
            ],
        }
        nodes, edges = build_layout(data)
        switch_tel = next(node for node in nodes if node.key == "switch")
        switch_datos = next(node for node in nodes if node.key == "switch_datos")
        phones = sorted(
            (node for node in nodes if node.key.startswith("team_") and "FANVIL" in node.label),
            key=lambda node: node.x,
        )
        ap = next(node for node in nodes if node.key.startswith("team_") and "Grandstream" in node.label)
        self.assertEqual(len(phones), 3)
        # Con espaciado sin solapes, los teléfonos pueden ir en 1 o 2 filas;
        # lo esencial es que NO se solapen entre sí.
        for _i in range(len(phones)):
            for _j in range(_i + 1, len(phones)):
                a, b = phones[_i], phones[_j]
                solapan = (a.x < b.x + b.width and b.x < a.x + a.width
                           and a.y < b.y + b.height and b.y < a.y + a.height)
                self.assertFalse(solapan)
        canvas_left, canvas_right = _canvas_bounds()
        mid = canvas_left + (canvas_right - canvas_left) // 2
        self.assertTrue(all(phone.x + phone.width < mid for phone in phones))
        self.assertGreater(ap.x, mid)
        self.assertGreater(switch_datos.x, switch_tel.x + switch_tel.width)
        router_switch_edges = [edge for edge in edges if edge.label in {"ETH3-LAN", "ETH4-LAN"}]
        self.assertEqual(len(router_switch_edges), 2)
        router_lanes = {
            edge.waypoints[0][1]
            for edge in router_switch_edges
            if edge.waypoints
        }
        self.assertEqual(len(router_lanes), 2)
        tel_bus_ys = {
            edge.waypoints[0][1]
            for edge in edges
            if edge.source == "switch" and edge.target.startswith("team_") and edge.waypoints
        }
        self.assertEqual(len(tel_bus_ys), len(phones))

    def test_two_switches_infer_con_switch_template(self) -> None:
        from generator.parser import infer_template

        data = {
            "equipos": [
                {"tipo": "switch", "modelo": "TP-LINK-5_PORTS", "cantidad": 1},
                {"tipo": "switch", "modelo": "TP-LINK-5_PORTS", "cantidad": 1},
                {"tipo": "wifi", "modelo": "Grandstream AP", "cantidad": 1},
            ]
        }
        infer_template(data)
        self.assertEqual(data["template"], "con_switch")

    def test_base_dect_appears_in_summary(self) -> None:
        data = {
            "internet": {},
            "router": {"modelo": ""},
            "ont": {"modelo": ""},
            "equipos": [
                {"tipo": "base_dect", "modelo": "W70B", "cantidad": 1},
                {"tipo": "terminal_dect", "modelo": "W71H", "cantidad": 1},
            ],
        }
        html = summarize_equipment(data)
        self.assertIn("W70B", html)
        self.assertIn("W71H", html)

    def test_ont_red_and_zte_for_euskaltel(self) -> None:
        base = {
            "cliente": "C", "cif": "B", "sede": "S", "direccion": "D",
            "template": "oficina_simple",
            "internet": {"tipo": "FIBRA", "velocidad": "600 MB", "proveedor": "Euskaltel"},
            "ont": {"modelo": "ONT ADAMO"},
            "router": {"modelo": "hAP ac3"},
            "equipos": [],
        }
        nodes, _ = build_layout(base)
        ont = next(n for n in nodes if n.key == "ont")
        self.assertEqual(ont.model, "ONT ZTE")
        self.assertIn("#d00000", ont.label)

    def test_ont_not_red_for_other_provider(self) -> None:
        base = {
            "cliente": "C", "cif": "B", "sede": "S", "direccion": "D",
            "template": "oficina_simple",
            "internet": {"tipo": "FIBRA", "velocidad": "600 MB", "proveedor": "AIRE"},
            "ont": {"modelo": "ONT ZTE"},
            "router": {"modelo": "hAP ac3"},
            "equipos": [],
        }
        nodes, _ = build_layout(base)
        ont = next(n for n in nodes if n.key == "ont")
        self.assertNotIn("#d00000", ont.label)


if __name__ == "__main__":
    unittest.main()
