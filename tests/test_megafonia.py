"""Altavoz de megafonia SIP (Grandstream GSC3506).

Articulo nuevo del catalogo. Se alimenta y conecta por PoE, asi que en el
diagrama tiene que colgar del switch como el resto de dispositivos de red, y
NO dibujarse como un telefono de sobremesa (lleva "Grandstream" en el nombre,
que es lo que despistaba al parser).
"""

import json
import unittest

from generator.aliases import resolve_alias
from generator.device_catalog import DEVICE_CATEGORIES, build_device_catalog
from generator.equipment_detection import _detect_device_category
from generator.layout_engine import build_layout
from generator.library_loader import load_library
from generator.parser import parse_equipment_line
from generator.web_adapter import form_to_data

MODELO = "Grandstream GSC3506"
LIBRERIA = "library/libreria_Ausarta_JUN_2026.xml"


class CatalogoTests(unittest.TestCase):
    def test_esta_en_el_catalogo_de_dispositivos(self) -> None:
        categoria = next((c for c in DEVICE_CATEGORIES if c["id"] == "megafonia"), None)
        self.assertIsNotNone(categoria)
        self.assertIn(MODELO, categoria["models"])
        # tipo "otro": es lo que hace que cuelgue del switch, como la camara.
        self.assertEqual(categoria["tipo"], "otro")

    def test_llega_al_desplegable_que_consume_el_frontend(self) -> None:
        ids = {c["id"] for c in build_device_catalog()}
        self.assertIn("megafonia", ids)

    def test_tiene_icono_propio_en_la_libreria(self) -> None:
        item = load_library(LIBRERIA).find(MODELO)
        self.assertIsNotNone(item, "falta assets/grandstream_gsc3506.png o su registro")
        self.assertTrue(item.data.startswith("data:image/png;base64,"))


class DeteccionTests(unittest.TestCase):
    def test_reconoce_los_nombres_que_manda_el_crm(self) -> None:
        for nombre in (
            "Grandstream - GSC3506 HORN SPEAKER",
            "GSC3506",
            "Altavoz SIP PoE exterior",
            "Bocina megafonia Grandstream",
        ):
            self.assertEqual(
                _detect_device_category(nombre),
                ("megafonia", "otro", MODELO),
                nombre,
            )

    def test_no_inventa_un_altavoz_cuando_solo_se_contrata_el_servicio(self) -> None:
        # "megafonia" a secas en una oferta suele ser el servicio, no el equipo.
        self.assertIsNone(_detect_device_category("Servicio de megafonia mensual"))
        self.assertIsNone(_detect_device_category("Cuota megafonia"))

    def test_no_se_confunde_con_un_telefono_grandstream(self) -> None:
        self.assertIsNone(_detect_device_category("Grandstream - GXP1610"))

    def test_alias_al_modelo_canonico(self) -> None:
        for texto in ("gsc3506", "GSC 3506", "grandstream gsc3506", "horn speaker"):
            self.assertEqual(resolve_alias(texto), MODELO, texto)

    def test_el_parser_no_lo_clasifica_como_telefono(self) -> None:
        self.assertEqual(parse_equipment_line(f"1 {MODELO}")["tipo"], "otro")
        self.assertEqual(parse_equipment_line("2 Altavoz SIP PoE")["tipo"], "otro")
        # Y los telefonos siguen siendo telefonos.
        self.assertEqual(parse_equipment_line("1 Grandstream GXP1610")["tipo"], "telefono")


class DiagramaTests(unittest.TestCase):
    def _data_con_switch(self, cantidad: int = 2) -> dict:
        devices = [
            {"category": "switch", "tipo": "switch", "modelo": "TP-Link TL-SG1008P",
             "cantidad": 1, "propiedad": "propio"},
            {"category": "megafonia", "tipo": "otro", "modelo": MODELO,
             "cantidad": cantidad, "propiedad": "propio"},
        ]
        return form_to_data({
            "cliente": "CLIENTE X",
            "sede": "Sede 1",
            "direccion": "Calle Mayor 1",
            "internet_tipo": "SOLO FIBRA",
            "internet_proveedor": "AIRE",
            "router_modelo": "MikroTik hAP ac3",
            "devices_json": json.dumps(devices),
        })

    def test_cuelga_del_switch(self) -> None:
        nodes, edges = build_layout(self._data_con_switch())
        altavoces = [n for n in nodes if MODELO in (n.model or "")]
        self.assertEqual(len(altavoces), 2)
        for altavoz in altavoces:
            origen = next((e.source for e in edges if e.target == altavoz.key), None)
            self.assertEqual(origen, "switch", f"{altavoz.key} no cuelga del switch")

    def test_el_diagrama_incluye_su_icono(self) -> None:
        from generator.web_adapter import build_drawio_from_data

        resultado = build_drawio_from_data(self._data_con_switch(1), LIBRERIA)
        self.assertIn(MODELO, resultado.result.xml)


if __name__ == "__main__":
    unittest.main()
