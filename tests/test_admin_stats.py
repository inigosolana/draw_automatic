import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from generator.glpi_client import GlpiError
from web.services.stats import build_admin_chart_periods, build_coverage_data


class AdminStatsTests(unittest.TestCase):
    def test_build_admin_chart_periods_single_pass(self) -> None:
        now = datetime(2026, 6, 15, 12, 0, 0)
        rows = [
            {"created_at": int(now.timestamp()), "technician_name": "Ana"},
            {"created_at": int(now.timestamp()), "technician_name": "Ana"},
            {"created_at": int((now - timedelta(days=2)).timestamp()), "technician_name": "Luis"},
            {"created_at": int((now - timedelta(days=40)).timestamp()), "technician_name": "Luis"},
            {"created_at": int((now - timedelta(days=400)).timestamp()), "technician_name": "Old"},
        ]

        result = build_admin_chart_periods(rows, now)

        self.assertEqual(result["week"]["total"], 3)
        self.assertEqual(result["week"]["values"][-1], 2)
        self.assertEqual(result["week"]["top"][0]["name"], "Ana")
        self.assertEqual(result["month"]["total"], 3)
        self.assertEqual(result["year"]["total"], 4)
        self.assertEqual(len(result["year"]["labels"]), 12)

    def test_build_coverage_data_assigns_province_technician(self) -> None:
        client = MagicMock()
        client.list_network_diagrams.return_value = [{"entities_id": 101}]
        catalog = [
            {
                "nombre": "Bizkaia",
                "clientes": [
                    {
                        "nombre": "Cliente A",
                        "sedes": [
                            {"id": 101, "nombre": "Sede cubierta", "direccion": "Dir 1"},
                            {"id": 102, "nombre": "Sede pendiente", "direccion": "Dir 2"},
                        ],
                    }
                ],
            }
        ]
        activity_rows = [
            {"entity_id": 102, "technician_name": "Tecnico Bizkaia"},
            {"entity_id": 102, "technician_name": "Tecnico Bizkaia"},
        ]

        result = build_coverage_data(catalog, client, activity_rows)

        assert result is not None
        self.assertEqual(result["total_sites"], 2)
        self.assertEqual(result["missing_sites"], 1)
        self.assertEqual(result["provinces"][0]["technician"], "Tecnico Bizkaia")
        self.assertEqual(result["provinces"][0]["clientes"][0]["sedes"][0]["entity_id"], 102)

    def test_build_coverage_data_returns_error_payload(self) -> None:
        client = MagicMock()
        client.list_network_diagrams.side_effect = GlpiError("fallo remoto")

        result = build_coverage_data([], client, [])

        self.assertIsNotNone(result)
        self.assertTrue(result["error"])


if __name__ == "__main__":
    unittest.main()
