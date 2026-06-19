import unittest

from generator.work_order_text_parser import parse_work_order_paste

SAMPLE_OT = """
CIF
B39357124
Nombre del cliente
Nort Iberian Control S.L
Prioridad:
Sí No
Número OT
OT00008850
Dirección de Instalación (Sede 1 - Oficina)
Calle Madrid, 8, 1, Oficina 4. Santander 39009, Cantabria
Contacto de sede
Marta - mizquierdo@northiberian.com - 679411967
Direcciones de fibra:
Fibra PRO Max Velocidad
CALLE Madrid, 8, 1, Oficina 4. Santander 39009, Cantabria
Trabajos a realizar
Fibra+BU
2 Puestos VOIP
VPN
Producto: Base DECT W70B
Producto: SIP-T31G
Producto: Cargador PSU 5V 600mA
Producto: W71H
Producto: GPON ONT
Producto: S53UG+5HaxD2HaxD-TC&RG650E-EU (CHATEAU 5G AX R17)
Cobertura:
Orange
Movistar(Aire)
"""

FULL_OT = """
CIF
B39357124
Nombre del cliente
Nort Iberian Control S.L
Prioridad:
Sí No
Número OT
OT00008850
Control Técnico
javier.bilbao
Configurador NOC
gorka.herrero
Técnico 1
urtzi.larrinaga
Técnico 2
--- Selecciona un tecnico ---
Comercial:
luisfernando.dhers
Dirección de Instalación (Sede 1 - Oficina)
Calle Madrid, 8, 1, Oficina 4. Santander 39009, Cantabria
Contacto de sede
Marta - mizquierdo@northiberian.com - 679411967
Teléfono
679411967
Direcciones de fibra:
Fibra PRO Max Velocidad
CALLE Madrid, 8, 1, Oficina 4. Santander 39009, Cantabria
Actuación
Instalación
Trabajos a realizar
Fibra+BU
2 Puestos VOIP
VPN
Producto: Base DECT W70B
Producto: SIP-T31G
Producto: Cargador PSU 5V 600mA
Producto: W71H
Producto: GPON ONT
Producto: S53UG+5HaxD2HaxD-TC&RG650E-EU (CHATEAU 5G AX R17)
Cobertura:
Orange
Movistar(Aire)
Diagrama de Red
Creada en: 24/04/2026 17:35
"""


class WorkOrderPasteTests(unittest.TestCase):
    def test_parses_nort_iberian_sample(self) -> None:
        result = parse_work_order_paste(SAMPLE_OT)

        self.assertEqual(result.cif, "B39357124")
        self.assertEqual(result.cliente, "Nort Iberian Control S.L")
        self.assertEqual(result.work_order_id, "8850")
        self.assertEqual(result.sede, "Oficina")
        self.assertIn("Calle Madrid", result.direccion)
        self.assertEqual(result.internet_tipo, "FIBRA + BACK UP")
        self.assertEqual(result.internet_proveedor, "AIRE")
        self.assertEqual(result.internet_velocidad, "1 GB")
        self.assertEqual(result.ont_modelo, "ONT ZTE")
        self.assertEqual(result.router_modelo, "CHATEAU")
        self.assertEqual(len(result.terminals), 2)
        self.assertEqual(result.terminals[0]["model"], "T-31")
        self.assertEqual(result.terminals[1]["model"], "W71H")
        self.assertEqual(result.terminals[1]["dect_base"], "W70B")
        self.assertTrue(any("Cargador" in warning for warning in result.warnings))

    def test_parses_full_screen_copy(self) -> None:
        result = parse_work_order_paste(FULL_OT)
        self.assertEqual(result.cif, "B39357124")
        self.assertEqual(result.cliente, "Nort Iberian Control S.L")
        self.assertEqual(result.work_order_id, "8850")
        self.assertEqual(len(result.terminals), 2)
        self.assertEqual(result.router_modelo, "CHATEAU")

    def test_parses_terminal_extensions_from_configuration_block(self) -> None:
        ot_text = """
CIF
B39357124
Nombre del cliente
Cliente Demo
Producto: SIP-T31G
Nombre del producto
SIP-T31G
Configuración
Extensión SIP: 2001
Producto: W71H
Configuración
2002
Producto: GPON ONT
"""
        result = parse_work_order_paste(ot_text)
        self.assertEqual(len(result.terminals), 2)
        self.assertEqual(result.terminals[0]["model"], "T-31")
        self.assertEqual(result.terminals[0]["extension"], "2001")
        self.assertEqual(result.terminals[1]["model"], "W71H")
        self.assertEqual(result.terminals[1]["extension"], "2002")

    def test_requires_text(self) -> None:
        with self.assertRaises(ValueError):
            parse_work_order_paste("   ")


if __name__ == "__main__":
    unittest.main()
