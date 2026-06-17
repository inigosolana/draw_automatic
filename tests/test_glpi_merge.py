import unittest

from generator.glpi_merge import merge_import_with_glpi


CATALOG = [
    {
        "nombre": "Cantabria",
        "clientes": [
            {
                "nombre": "Nort Iberian Control",
                "cif": "B39357124",
                "direccion": "Santander, Cantabria",
                "sedes": [
                    {
                        "id": 501,
                        "nombre": "Oficina",
                        "direccion": "Santander 39009, Cantabria",
                    },
                    {
                        "id": 502,
                        "nombre": "Almacén",
                        "direccion": "Polígono industrial, Santander",
                    },
                ],
            }
        ],
    }
]


class GlpiMergeTests(unittest.TestCase):
    def test_merges_client_and_keeps_detailed_offer_address(self) -> None:
        merged = merge_import_with_glpi(
            {
                "cliente": "Nort Iberian Control S.L",
                "cif": "B39357124",
                "sede": "Sede 1 - Oficina",
                "direccion": "Calle Madrid, 8, 1, Oficina 4. Santander 39009, Cantabria",
            },
            CATALOG,
        )

        self.assertTrue(merged["matched"])
        self.assertEqual(merged["glpi_entity_id"], "501")
        self.assertEqual(merged["cliente"], "Nort Iberian Control")
        self.assertEqual(merged["cif"], "B39357124")
        self.assertEqual(merged["sede"], "Oficina")
        self.assertIn("Calle Madrid", merged["direccion"])
        self.assertTrue(any(item["field"] == "cliente" for item in merged["corrections"]))
        self.assertTrue(any(item["field"] == "sede" for item in merged["corrections"]))

    def test_uses_glpi_when_offer_has_no_address(self) -> None:
        merged = merge_import_with_glpi(
            {
                "cliente": "Nort Iberian Control S.L",
                "cif": "B39357124",
                "sede": "Oficina",
                "direccion": "",
            },
            CATALOG,
        )
        self.assertEqual(merged["direccion"], "Santander 39009, Cantabria")


if __name__ == "__main__":
    unittest.main()
