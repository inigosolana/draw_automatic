import unittest
from unittest.mock import MagicMock

from generator.glpi_client import GlpiError
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

        diagram_id, url, name = publish_diagram(
            client, stores,
            entity_id=7, diagram_name="Cliente - Sede",
            client_name="Cliente", site_name="Sede",
            technician={"name": "Ana"}, source="Generado", graph_xml="<mxfile/>",
        )

        self.assertEqual(diagram_id, 99)
        self.assertEqual(url, "http://glpi/diagram/99")
        self.assertEqual(name, "Cliente - Sede")
        stores.activity.add.assert_called_once()
        stores.catalog.clear.assert_any_call("admin_coverage")

    def test_renames_and_retries_when_glpi_rejects_the_name(self) -> None:
        """El caso GOIZTIRI: GLPI rechaza por duplicado y la app reescribe."""
        client = MagicMock()
        client.create_network_diagram.side_effect = [
            GlpiError(
                "GLPI ha rechazado la operacion (codigo 400): ERROR_GLPI_ADD "
                "Duplicate entry 'ASOC GOIZTIRI - Sede 2' for key "
                "'glpi_plugin_archimap_graphs.name_UNIQUE'"
            ),
            99,
        ]
        client.diagram_url.return_value = "http://glpi/diagram/99"
        stores = MagicMock()

        diagram_id, _url, name = publish_diagram(
            client, stores,
            entity_id=7, diagram_name="ASOC GOIZTIRI - Sede 2",
            client_name="Cliente", site_name="Sede 2",
            technician={"name": "Ana"}, source="Draw subido", graph_xml="<mxfile/>",
        )

        self.assertEqual(diagram_id, 99)
        self.assertEqual(client.create_network_diagram.call_count, 2)
        # El nombre devuelto es el reescrito, no el que GLPI rechazo.
        self.assertNotEqual(name, "ASOC GOIZTIRI - Sede 2")
        self.assertLessEqual(len(name), 45)
        stores.activity.add.assert_called_once()

    def test_shortens_and_retries_when_the_name_is_too_long(self) -> None:
        client = MagicMock()
        client.create_network_diagram.side_effect = [
            GlpiError(
                "GLPI ha rechazado la operacion (codigo 400): ERROR_GLPI_ADD "
                "Data too long for column 'name' at row 1"
            ),
            101,
        ]
        client.diagram_url.return_value = "http://glpi/diagram/101"
        stores = MagicMock()

        diagram_id, _url, name = publish_diagram(
            client, stores,
            entity_id=7, diagram_name="X" * 80,
            client_name="Cliente", site_name="Sede 1",
            technician={"name": "Ana"}, source="Draw subido", graph_xml="<mxfile/>",
        )

        self.assertEqual(diagram_id, 101)
        self.assertLessEqual(len(name), 45)

    def test_other_glpi_errors_are_not_retried(self) -> None:
        client = MagicMock()
        client.create_network_diagram.side_effect = GlpiError("No se ha podido conectar con GLPI.")
        with self.assertRaises(GlpiError):
            publish_diagram(
                client, MagicMock(),
                entity_id=7, diagram_name="Cliente - Sede",
                client_name="Cliente", site_name="Sede",
                technician={"name": "Ana"}, source="Generado", graph_xml="<mxfile/>",
            )
        self.assertEqual(client.create_network_diagram.call_count, 1)


class DectParsingTests(unittest.TestCase):
    def test_w90dm_is_base_dect(self) -> None:
        from generator.parser import parse_equipment_line
        self.assertEqual(parse_equipment_line("1 Yealink W90DM").get("tipo"), "base_dect")
        self.assertEqual(parse_equipment_line("1 W90DM").get("tipo"), "base_dect")
        self.assertEqual(parse_equipment_line("1 W73H").get("tipo"), "terminal_dect")


class CoverageClientLevelTests(unittest.TestCase):
    def test_site_covered_when_client_has_diagram(self) -> None:
        from web.services.stats import build_missing_sites_rows
        catalog = [{
            "nombre": "Bizkaia",
            "clientes": [{
                "id": 478, "nombre": "Manuela Simón",
                "sedes": [
                    {"id": 5001, "nombre": "Sede 1", "direccion": "X"},
                    {"id": 5002, "nombre": "Sede 2", "direccion": "Y"},
                ],
            }],
        }]
        # El diagrama cuelga del cliente (478), no de las sedes -> ambas cubiertas.
        rows = build_missing_sites_rows(catalog, {478})
        self.assertEqual(rows, [])
        # Sin cobertura del cliente ni de las sedes -> las dos salen como pendientes.
        self.assertEqual(len(build_missing_sites_rows(catalog, set())), 2)
        # Diagrama a nivel sede tambien cuenta.
        self.assertEqual(len(build_missing_sites_rows(catalog, {5001})), 1)


if __name__ == "__main__":
    unittest.main()
