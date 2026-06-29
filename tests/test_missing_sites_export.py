import unittest

from web.services.export import missing_sites_to_xlsx
from web.services.stats import build_missing_sites_rows


class MissingSitesExportTests(unittest.TestCase):
    def test_missing_sites_to_xlsx_builds_workbook(self) -> None:
        catalog = [
            {
                "nombre": "Bizkaia",
                "clientes": [
                    {
                        "nombre": "Cliente A",
                        "sedes": [{"id": 102, "nombre": "Sede X", "direccion": "Calle 1"}],
                    }
                ],
            }
        ]
        rows = build_missing_sites_rows(catalog, set())
        payload = missing_sites_to_xlsx(rows)

        self.assertTrue(payload.startswith(b"PK"))
        self.assertGreater(len(payload), 100)


if __name__ == "__main__":
    unittest.main()
