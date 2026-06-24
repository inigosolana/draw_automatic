import unittest
from datetime import datetime

from generator.diagram_metadata import (
    build_diagram_description,
    diagram_base_name,
    diagram_source_meta,
    enrich_diagram_row,
    unique_diagram_name,
    versioned_diagram_name,
)


class DiagramMetadataTests(unittest.TestCase):
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
