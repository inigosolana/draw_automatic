import unittest

from generator.web_adapter import (
    _as_qty,
    _expand_terminal_equipment,
    _parse_router_ip,
    form_to_data,
    form_to_structured_data,
    sanitize_filename,
    structured_to_generator_data,
)


class AsQtyTests(unittest.TestCase):
    def test_tolerant_of_garbage(self) -> None:
        self.assertEqual(_as_qty(3), 3)
        self.assertEqual(_as_qty("4"), 4)
        self.assertEqual(_as_qty(None), 1)
        self.assertEqual(_as_qty(""), 1)
        self.assertEqual(_as_qty("abc"), 1)
        self.assertEqual(_as_qty(0), 1)
        self.assertEqual(_as_qty(-5), 1)


class SanitizeFilenameTests(unittest.TestCase):
    def test_strips_unsafe_chars_and_keeps_extension(self) -> None:
        name = sanitize_filename("Cliente / S.L.", "Sede #1")
        self.assertTrue(name.endswith(".drawio"))
        self.assertNotIn("/", name)
        self.assertNotIn("#", name)

    def test_empty_falls_back(self) -> None:
        self.assertEqual(sanitize_filename("", ""), "drawio_output.drawio")


class ParseRouterIpTests(unittest.TestCase):
    def test_splits_model_and_ip_on_dash(self) -> None:
        model, ip = _parse_router_ip("hAP ac3 - 192.168.1.1")
        self.assertEqual(model, "hAP ac3")
        self.assertEqual(ip, "192.168.1.1")

    def test_keeps_existing_ip_when_no_dash(self) -> None:
        model, ip = _parse_router_ip("hAP ac3", "10.0.0.1")
        self.assertEqual(model, "hAP ac3")
        self.assertEqual(ip, "10.0.0.1")

    def test_empty_returns_current_ip(self) -> None:
        model, ip = _parse_router_ip("", "10.0.0.1")
        self.assertEqual(model, "")
        self.assertEqual(ip, "10.0.0.1")


class ExpandTerminalEquipmentTests(unittest.TestCase):
    def test_expands_phones_by_quantity_with_extensions(self) -> None:
        equipos = [
            {"tipo": "telefono", "modelo": "T31P", "cantidad": 2, "extensiones": ["101", "102"]},
        ]
        expanded = _expand_terminal_equipment(equipos, details=[])
        self.assertEqual(len(expanded), 2)
        self.assertEqual([item["cantidad"] for item in expanded], [1, 1])
        self.assertEqual([item.get("extension") for item in expanded], ["101", "102"])

    def test_non_terminal_passthrough(self) -> None:
        equipos = [{"tipo": "switch", "modelo": "GS108", "cantidad": 3}]
        expanded = _expand_terminal_equipment(equipos, details=[])
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0]["cantidad"], 3)


class FormRoundTripTests(unittest.TestCase):
    BASE_FORM = {
        "cliente": "Cliente Demo",
        "cif": "B12345678",
        "sede": "Sede Central",
        "direccion": "Calle Mayor, 1",
        "internet_tipo": "FIBRA",
        "internet_velocidad": "600",
        "internet_proveedor": "Telefonica",
        "ont_modelo": "ONT ZTE",
        "router_modelo": "hAP ac3",
        "router_ip": "192.168.1.1",
    }

    def test_structured_then_generator_preserves_core_fields(self) -> None:
        structured = form_to_structured_data(self.BASE_FORM)
        legacy = structured_to_generator_data(structured)
        self.assertEqual(legacy["cliente"], "Cliente Demo")
        self.assertEqual(legacy["sede"], "Sede Central")
        self.assertEqual(legacy["direccion"], "Calle Mayor, 1")
        self.assertEqual(legacy["router"]["modelo"], "hAP ac3")
        self.assertEqual(legacy["internet"]["proveedor"], "Telefonica")

    def test_form_to_data_is_the_two_step_pipeline(self) -> None:
        direct = form_to_data(self.BASE_FORM)
        composed = structured_to_generator_data(form_to_structured_data(self.BASE_FORM))
        self.assertEqual(direct, composed)

    def _dect_form(self, detail_lines: list[str], equipment_lines: list[str]) -> dict:
        return {
            "cliente": "MEGAMOTOR SL",
            "sede": "Sede 1 - Santander",
            "direccion": "Avenida Parayas 42",
            "internet_tipo": "SOLO FIBRA",
            "internet_proveedor": "AIRE",
            "terminal_equipment_text": "\n".join(equipment_lines),
            "terminal_details": "\n".join(detail_lines),
        }

    def test_dect_base_keeps_its_own_serial_and_does_not_shift_the_rest(self) -> None:
        """La base DECT consume SU linea de detalle.

        Antes no la consumia: la base salia sin S/N ni MAC y todos los detalles
        siguientes se corrian una posicion, asi que el S/N de la base acababa
        etiquetando al primer inalambrico y el ultimo se quedaba sin numero.
        """
        form = self._dect_form(
            [
                "W70B |  | BASE1 | C4:FC:22:6E:2F:96 |  | propio | W70B |  |  | ",
                "W71H | 3001 | HS1 |  |  | propio | W70B |  |  | ",
                "W71H | 3002 | HS2 |  |  | propio | W70B |  |  | ",
            ],
            [
                "1 W70B propio",
                "1 W71H, extension 3001, base W70B propio",
                "1 W71H, extension 3002, base W70B propio",
            ],
        )
        equipos = form_to_data(form)["equipos"]
        base = next(e for e in equipos if e["tipo"] == "base_dect")
        self.assertEqual(base["serial_number"], "BASE1")
        self.assertEqual(base["mac"], "C4:FC:22:6E:2F:96")
        handsets = [e for e in equipos if e["tipo"] == "terminal_dect"]
        self.assertEqual([h["serial_number"] for h in handsets], ["HS1", "HS2"])
        self.assertEqual([h["extensiones"] for h in handsets], [["3001"], ["3002"]])

    def test_two_dect_bases_keep_their_units_through_the_form(self) -> None:
        """OT 9342: dos W70B y 9 inalambricos repartidos 5/4 llegan al layout."""
        from generator.layout_engine import build_layout

        details = [
            "W70B |  | BASE1 | C4:FC:22:6E:2F:96 |  | propio | W70B-1 |  |  | ",
            "W70B |  | BASE2 | C4:FC:22:6E:2F:DF |  | propio | W70B-2 |  |  | ",
        ]
        equipment = ["1 W70B, base W70B-1 propio", "1 W70B, base W70B-2 propio"]
        for index in range(9):
            unit = "W70B-1" if index < 5 else "W70B-2"
            details.append(f"W71H | 325{index} | HS{index} |  |  | propio | {unit} |  |  | ")
            equipment.append(f"1 W71H, extension 325{index}, base {unit} propio")

        data = form_to_data(self._dect_form(details, equipment))
        bases = [e for e in data["equipos"] if e["tipo"] == "base_dect"]
        self.assertEqual([b["dect_base"] for b in bases], ["W70B-1", "W70B-2"])
        self.assertEqual([b["serial_number"] for b in bases], ["BASE1", "BASE2"])

        nodes, edges = build_layout(data)
        base_nodes = [n for n in nodes if n.meta and n.meta.get("dect_role") == "base"]
        self.assertEqual(len(base_nodes), 2)
        handset_keys = {n.key for n in nodes if n.meta and n.meta.get("dect_role") == "handset"}
        per_base: dict[str, int] = {}
        for edge in edges:
            if edge.target in handset_keys:
                per_base[edge.source] = per_base.get(edge.source, 0) + 1
        self.assertEqual(sorted(per_base.values()), [4, 5])

    def test_solo_4g_forces_chateau_and_capacity(self) -> None:
        form = dict(self.BASE_FORM)
        form["internet_tipo"] = "SOLO 4G MONITORIZADO"
        form["internet_velocidad"] = "100"
        legacy = form_to_data(form)
        self.assertEqual(legacy["router"]["modelo"], "CHATEAU")
        self.assertEqual(legacy["internet"]["capacidad"], "100")
        self.assertEqual(legacy["internet"]["velocidad"], "")
        self.assertEqual(legacy["ont"]["modelo"], "")


if __name__ == "__main__":
    unittest.main()
