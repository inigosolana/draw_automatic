import unittest

from generator.glpi_merge import find_glpi_suggestions, merge_import_with_glpi


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
            },
            {
                "nombre": "Nort Control Iberia",
                "cif": "B11111111",
                "direccion": "Torrelavega, Cantabria",
                "sedes": [
                    {
                        "id": 601,
                        "nombre": "Central",
                        "direccion": "Torrelavega 39300",
                    },
                ],
            },
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
        self.assertEqual(merged["confidence"], "high")
        self.assertEqual(merged["glpi_entity_id"], "501")
        self.assertEqual(merged["cliente"], "Nort Iberian Control")
        self.assertEqual(merged["cif"], "B39357124")
        self.assertEqual(merged["sede"], "Oficina")
        self.assertIn("Calle Madrid", merged["direccion"])
        self.assertTrue(any(item["field"] == "cliente" for item in merged["corrections"]))
        self.assertTrue(any(item["field"] == "sede" for item in merged["corrections"]))

    def test_keeps_crm_address_when_glpi_differs(self) -> None:
        merged = merge_import_with_glpi(
            {
                "cliente": "Nort Iberian Control S.L",
                "cif": "B39357124",
                "sede": "Oficina",
                "direccion": "Calle Nueva, 5, Bajo. Fuensanta, Pinos Puente 18328, Granada",
            },
            CATALOG,
        )
        self.assertEqual(merged["glpi_entity_id"], "501")
        self.assertIn("Calle Nueva", merged["direccion"])
        self.assertTrue(
            any(
                item["field"] == "direccion" and item["source"] == "CRM"
                for item in merged["corrections"]
            )
        )
        self.assertIn("GLPI tenía otra distinta", merged["message"])

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

    def test_suggests_similar_clients_when_no_exact_match(self) -> None:
        merged = merge_import_with_glpi(
            {
                "cliente": "Iberian Control Norte",
                "cif": "",
                "sede": "Central",
                "direccion": "Torrelavega",
            },
            CATALOG,
        )
        self.assertFalse(merged["matched"])
        self.assertIn(merged["confidence"], ("low", "none"))
        self.assertGreaterEqual(len(merged["suggestions"]), 1)

    def test_find_glpi_suggestions_ranks_by_name_similarity(self) -> None:
        suggestions = find_glpi_suggestions(
            {
                "cliente": "Nort Control",
                "cif": "",
                "sede": "Central",
                "direccion": "Torrelavega",
            },
            CATALOG,
            limit=3,
        )
        self.assertGreaterEqual(len(suggestions), 1)
        names = {item["cliente"] for item in suggestions}
        self.assertTrue("Nort Control Iberia" in names or "Nort Iberian Control" in names)


    def test_never_remaps_sede_to_a_different_one(self) -> None:
        # CIF exacto: la sede de la OT debe respetarse, no cambiarse por otra
        # sede distinta del mismo cliente (bug «Sede 1 - COLEGIO» -> «Sede 2 - ...»).
        catalog = [
            {
                "nombre": "Cantabria",
                "clientes": [
                    {
                        "id": 10,
                        "nombre": "CEIP EL SARDINERO",
                        "cif": "P3900000A",
                        "sedes": [
                            {"id": 101, "nombre": "Sede 1 - COLEGIO", "direccion": "Calle Trasmiera 9"},
                            {"id": 102, "nombre": "Sede 2 - PREESCOLAR", "direccion": "Calle Santander 9B"},
                        ],
                    }
                ],
            }
        ]
        merged = merge_import_with_glpi(
            {"cliente": "CEIP EL SARDINERO", "cif": "P3900000A",
             "sede": "Sede 1 - COLEGIO", "direccion": "Calle Trasmiera 9"},
            catalog,
        )
        self.assertEqual(merged["sede"], "Sede 1 - COLEGIO")
        self.assertEqual(merged["glpi_entity_id"], "101")
        sede_corrs = [c for c in merged["corrections"] if c["field"] == "sede"]
        self.assertEqual(sede_corrs, [])

    def test_same_sede_adopts_glpi_prefix(self) -> None:
        # Si es la MISMA sede, sí se adopta el nombre de GLPI (añade «Sede N - »).
        catalog = [
            {
                "nombre": "Cantabria",
                "clientes": [
                    {
                        "id": 10,
                        "nombre": "CEIP EL SARDINERO",
                        "cif": "P3900000A",
                        "sedes": [
                            {"id": 102, "nombre": "Sede 2 - PREESCOLAR", "direccion": "x"},
                        ],
                    }
                ],
            }
        ]
        merged = merge_import_with_glpi(
            {"cliente": "CEIP EL SARDINERO", "cif": "P3900000A",
             "sede": "PREESCOLAR", "direccion": "x"},
            catalog,
        )
        self.assertEqual(merged["sede"], "Sede 2 - PREESCOLAR")
        self.assertEqual(merged["glpi_entity_id"], "102")


if __name__ == "__main__":
    unittest.main()
