import unittest

from generator.address_formatter import normalize_street_address, to_glpi_ascii


class AddressFormatterTests(unittest.TestCase):
    def test_strips_city_and_keeps_calle_rua(self) -> None:
        raw = "Calle Rua, 13, Local. León 24003, Leon"
        self.assertEqual(normalize_street_address(raw), "Calle Rua, 13, Local")

    def test_keeps_neighborhood_street_without_city_tail(self) -> None:
        raw = "Calle Nueva, 5, Bajo. Fuensanta, Pinos Puente 18328, Granada"
        self.assertEqual(normalize_street_address(raw), "Calle Nueva, 5, Bajo")

    def test_keeps_office_detail_without_city(self) -> None:
        raw = "Calle Madrid, 8, 1, Oficina 4. Santander 39009, Cantabria"
        self.assertEqual(normalize_street_address(raw), "Calle Madrid, 8, 1, Oficina 4")

    def test_leaves_short_address_untouched(self) -> None:
        self.assertEqual(normalize_street_address("Calle Portal De Zurbano, 19"), "Calle Portal De Zurbano, 19")

    def test_to_glpi_ascii_removes_accents_and_enye(self) -> None:
        self.assertEqual(to_glpi_ascii("León"), "Leon")
        self.assertEqual(to_glpi_ascii("Niño"), "Nino")
        self.assertEqual(to_glpi_ascii("Calle José García"), "Calle Jose Garcia")

    def test_empty_input(self) -> None:
        self.assertEqual(normalize_street_address(""), "")
        self.assertEqual(normalize_street_address("   "), "")


if __name__ == "__main__":
    unittest.main()
