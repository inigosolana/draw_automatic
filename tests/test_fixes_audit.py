import unittest
from unittest.mock import MagicMock

from generator.web_adapter import _as_qty
from web.services.diagram_publish import publish_diagram


class AsQtyTests(unittest.TestCase):
    def test_tolerant_quantities(self) -> None:
        self.assertEqual(_as_qty(3), 3)
        self.assertEqual(_as_qty("4"), 4)
        self.assertEqual(_as_qty(None), 1)      # antes lanzaba TypeError
        self.assertEqual(_as_qty("abc"), 1)     # antes lanzaba ValueError
        self.assertEqual(_as_qty(0), 1)         # mínimo 1
        self.assertEqual(_as_qty(-2), 1)


class PublishDiagramTests(unittest.TestCase):
    def test_publishes_and_invalidates_coverage_cache(self) -> None:
        client = MagicMock()
        client.create_network_diagram.return_value = 99
        client.diagram_url.return_value = "http://glpi/diagram/99"
        stores = MagicMock()

        diagram_id, url = publish_diagram(
            client, stores,
            entity_id=7, diagram_name="Cliente - Sede",
            client_name="Cliente", site_name="Sede",
            technician={"name": "Ana"}, source="Generado", graph_xml="<mxfile/>",
        )

        self.assertEqual(diagram_id, 99)
        self.assertEqual(url, "http://glpi/diagram/99")
        stores.activity.add.assert_called_once()
        stores.catalog.clear.assert_any_call("admin_coverage")


class DectParsingTests(unittest.TestCase):
    def test_w90dm_is_base_dect(self) -> None:
        from generator.parser import parse_equipment_line
        self.assertEqual(parse_equipment_line("1 Yealink W90DM").get("tipo"), "base_dect")
        self.assertEqual(parse_equipment_line("1 W90DM").get("tipo"), "base_dect")
        self.assertEqual(parse_equipment_line("1 W73H").get("tipo"), "terminal_dect")


if __name__ == "__main__":
    unittest.main()
