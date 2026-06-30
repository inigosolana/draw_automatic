"""Tests de caracterización del flujo OT completo: pegar OT → parsear → cruzar
con el catálogo de GLPI. Congelan el comportamiento actual de la zona de parsing
de OT (work_order_text_parser + glpi_merge) como red de seguridad antes de
cualquier refactor de esa zona densa.
"""

import unittest

from generator.glpi_merge import merge_import_with_glpi
from generator.work_order_text_parser import parse_work_order_paste

OT_NORT_IBERIAN = """
CIF
B39357124
Nombre del cliente
Nort Iberian Control S.L
Número OT
OT00008850
Dirección de Instalación (Sede 1 - Oficina)
Calle Madrid, 8, 1, Oficina 4. Santander 39009, Cantabria
Direcciones de fibra:
Fibra PRO Max Velocidad
CALLE Madrid, 8, 1, Oficina 4. Santander 39009, Cantabria
Trabajos a realizar
Fibra+BU
2 Puestos VOIP
Producto: Base DECT W70B
Producto: SIP-T31G
Producto: W71H
Producto: GPON ONT
Producto: S53UG+5HaxD2HaxD-TC&RG650E-EU (CHATEAU 5G AX R17)
Cobertura:
Movistar(Aire)
"""

CATALOG = [
    {
        "nombre": "Cantabria",
        "clientes": [
            {
                "nombre": "Nort Iberian Control",
                "cif": "B39357124",
                "direccion": "Santander, Cantabria",
                "sedes": [
                    {"id": 501, "nombre": "Oficina", "direccion": "Santander 39009, Cantabria"},
                ],
            }
        ],
    }
]


class OtPipelineCharacterizationTests(unittest.TestCase):
    def test_paste_then_merge_locks_full_flow(self) -> None:
        parsed = parse_work_order_paste(OT_NORT_IBERIAN)

        # Parsing (caracterización del estado actual).
        self.assertEqual(parsed.cif, "B39357124")
        self.assertEqual(parsed.internet_tipo, "FIBRA + BACK UP")
        self.assertEqual(parsed.router_modelo, "CHATEAU")
        self.assertEqual(parsed.ont_modelo, "ONT ZTE")
        self.assertEqual(len(parsed.terminals), 2)

        merged = merge_import_with_glpi(
            {
                "cliente": parsed.cliente,
                "cif": parsed.cif,
                "sede": parsed.sede,
                "direccion": parsed.direccion,
            },
            CATALOG,
        )

        # Cruce con GLPI: CIF coincide → match alto, gana la dirección detallada
        # de la OT y se corrige el nombre canónico de GLPI.
        self.assertTrue(merged["matched"])
        self.assertEqual(merged["confidence"], "high")
        self.assertEqual(merged["glpi_entity_id"], "501")
        self.assertEqual(merged["cliente"], "Nort Iberian Control")
        self.assertIn("Calle Madrid", merged["direccion"])

    def test_merge_without_catalog_is_passthrough(self) -> None:
        parsed = parse_work_order_paste(OT_NORT_IBERIAN)
        merged = merge_import_with_glpi(
            {"cliente": parsed.cliente, "cif": parsed.cif, "sede": parsed.sede, "direccion": parsed.direccion},
            [],
        )
        self.assertFalse(merged["matched"])
        self.assertEqual(merged["cif"], "B39357124")
        self.assertIn("GLPI no disponible", merged["message"])


if __name__ == "__main__":
    unittest.main()
