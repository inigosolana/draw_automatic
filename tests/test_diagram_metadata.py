import unittest
from datetime import datetime

from generator.diagram_metadata import (
    GLPI_NAME_MAX,
    build_diagram_description,
    diagram_base_name,
    diagram_source_meta,
    enrich_diagram_row,
    fit_diagram_name,
    suffixed_diagram_name,
    unique_diagram_name,
    versioned_diagram_name,
)

# Los tres ficheros que GLPI rechazaba: el nombre del cliente por si solo ya
# ocupa los 45 caracteres de la columna, asi que al truncar a lo bruto las tres
# sedes quedaban con el MISMO nombre y el UNIQUE global tumbaba la segunda.
GOIZTIRI = [
    "ASOCIACION_GOIZTIRI_ELKARTEA_DE_ACCION_SOCIAL_CALLE_BIZKAIA_30_BARAKALDO_SEDE_2",
    "ASOCIACION_GOIZTIRI_ELKARTEA_DE_ACCION_SOCIAL_SAN_JOSE_11_BARAKALDO_SEDE_3",
    "ASOCIACION_GOIZTIRI_ELKARTEA_DE_ACCION_SOCIAL_SAN_JUAN_13_BARAKALDO_SEDE_5",
]


class FitDiagramNameTests(unittest.TestCase):
    def test_keeps_short_names_untouched(self) -> None:
        self.assertEqual(fit_diagram_name("Cliente Corto - Sede 1"), "Cliente Corto - Sede 1")

    def test_fits_in_glpi_column(self) -> None:
        for raw in GOIZTIRI:
            self.assertLessEqual(len(fit_diagram_name(raw)), GLPI_NAME_MAX, raw)

    def test_sites_of_same_client_get_different_names(self) -> None:
        names = {fit_diagram_name(raw) for raw in GOIZTIRI}
        self.assertEqual(len(names), len(GOIZTIRI), names)

    def test_keeps_client_site_and_street(self) -> None:
        name = fit_diagram_name(GOIZTIRI[0])
        self.assertIn("GOIZTIRI", name)
        self.assertIn("Sede 2", name)
        self.assertIn("BIZKAIA", name)
        self.assertIn("30", name)

    def test_site_number_survives_even_with_a_huge_client_name(self) -> None:
        raw = "A" * 90 + " CALLE MAYOR 1 BILBAO SEDE 7"
        name = fit_diagram_name(raw)
        self.assertLessEqual(len(name), GLPI_NAME_MAX)
        self.assertIn("Sede 7", name)

    def test_street_number_is_not_left_orphan_without_a_via_word(self) -> None:
        # "SAN JUAN 13": sin la palabra CALLE, el corte no debe quedarse solo
        # con el numero.
        self.assertIn("SAN JUAN 13", fit_diagram_name(GOIZTIRI[2]))


class SuffixedDiagramNameTests(unittest.TestCase):
    def test_suffix_fits_and_changes_the_name(self) -> None:
        base = "ASOC GOIZTIRI - Sede 2 C/ BIZKAIA 30"
        name = suffixed_diagram_name(base)
        self.assertLessEqual(len(name), GLPI_NAME_MAX)
        self.assertNotEqual(name.lower(), base.lower())

    def test_avoids_names_already_taken(self) -> None:
        base = "Cliente - Sede 1"
        first = suffixed_diagram_name(base)
        second = suffixed_diagram_name(base, {first.lower()})
        self.assertNotEqual(first, second)
        self.assertLessEqual(len(second), GLPI_NAME_MAX)


class VersionedNameTests(unittest.TestCase):
    def test_version_of_a_long_name_keeps_the_site(self) -> None:
        """La copia fechada tambien conserva la sede.

        Antes se cortaba por el caracter N y la version de la Sede 2 y la de la
        Sede 5 quedaban con el mismo nombre base.
        """
        when = datetime(2026, 6, 23, 15, 30, 45)
        names = {versioned_diagram_name(raw, when=when) for raw in GOIZTIRI}
        self.assertEqual(len(names), len(GOIZTIRI), names)
        for name in names:
            self.assertLessEqual(len(name), GLPI_NAME_MAX, name)
        self.assertTrue(any("Sede 2" in name for name in names), names)


class DiagramMetadataTests(unittest.TestCase):
    def test_unique_diagram_name_detects_duplicate_from_another_site(self) -> None:
        # El diagrama ya subido de la Sede 3 no debe bloquear a la Sede 5:
        # el nombre se reescribe en vez de dejar que GLPI lo rechace.
        taken = fit_diagram_name(GOIZTIRI[1])
        name = unique_diagram_name(GOIZTIRI[1], [{"name": taken}])
        self.assertNotEqual(name.lower(), taken.lower())
        self.assertLessEqual(len(name), GLPI_NAME_MAX)

    def test_unique_diagram_name_adds_timestamp_when_duplicate(self) -> None:
        existing = [{"name": "Cliente - Sede"}]
        name = unique_diagram_name("Cliente - Sede", existing)
        self.assertNotEqual(name, "Cliente - Sede")
        self.assertLessEqual(len(name), 45)

    def test_diagram_base_name_strips_version_suffix(self) -> None:
        self.assertEqual(
            diagram_base_name("Cliente - Sede_20260623_153045"),
            "Cliente - Sede",
        )
        self.assertEqual(
            diagram_base_name("Cliente - Sede_20260623_153045.drawio"),
            "Cliente - Sede",
        )

    def test_versioned_diagram_name_appends_modification_stamp(self) -> None:
        when = datetime(2026, 6, 23, 15, 30, 45)
        name = versioned_diagram_name("Cliente - Sede", when=when)
        self.assertEqual(name, "Cliente - Sede_20260623_153045")
        self.assertLessEqual(len(name), 45)

    def test_build_diagram_description_includes_source_technician_and_date(self) -> None:
        description = build_diagram_description(
            client_name="Cliente",
            site_name="Sede 1",
            technician={"name": "Ana Garcia", "username": "ag"},
            source="Generado",
            filename="demo.drawio",
        )
        self.assertIn("Generado", description)
        self.assertIn("Ana Garcia", description)
        self.assertIn("Cliente - Sede 1", description)
        self.assertIn("demo.drawio", description)

    def test_enrich_diagram_row_uses_activity_metadata(self) -> None:
        row = enrich_diagram_row(
            {"id": 12, "name": "Demo"},
            {
                12: {
                    "created_at": 1_700_000_000.0,
                    "technician_name": "Tecnico A",
                    "source": "Archivo antiguo",
                }
            },
        )
        self.assertEqual(row["technician"], "Tecnico A")
        self.assertEqual(row["source"], "Archivo antiguo")
        self.assertRegex(row["created_label"], r"\d{2}/\d{2}/\d{4}")

    def test_diagram_source_meta_maps_uploaded_sources(self) -> None:
        uploaded = diagram_source_meta("Draw subido")
        legacy = diagram_source_meta("Archivo antiguo")
        generated = diagram_source_meta("Generado")
        self.assertEqual(uploaded["key"], "subido")
        self.assertEqual(legacy["key"], "subido")
        self.assertEqual(generated["key"], "generado")


if __name__ == "__main__":
    unittest.main()
