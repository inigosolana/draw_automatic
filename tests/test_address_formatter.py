import unittest

from generator.address_formatter import normalize_street_address


class AddressFormatterTests(unittest.TestCase):
    def test_strips_city_and_postcode_suffix(self) -> None:
        raw = "Calle Rua, 13, Local. León 24003, Leon"
        self.assertEqual(normalize_street_address(raw), "Rúa, 13, Local")

    def test_keeps_neighborhood_street_without_city_tail(self) -> None:
        raw = "Calle Nueva, 5, Bajo. Fuensanta, Pinos Puente 18328, Granada"
        self.assertEqual(normalize_street_address(raw), "Calle Nueva, 5, Bajo")

    def test_keeps_office_detail_without_city(self) -> None:
        raw = "Calle Madrid, 8, 1, Oficina 4. Santander 39009, Cantabria"
        self.assertEqual(normalize_street_address(raw), "Calle Madrid, 8, 1, Oficina 4")

    def test_leaves_short_address_untouched(self) -> None:
        self.assertEqual(normalize_street_address("Calle Portal De Zurbano, 19"), "Calle Portal De Zurbano, 19")

    def test_empty_input(self) -> None:
        self.assertEqual(normalize_street_address(""), "")
        self.assertEqual(normalize_street_address("   "), "")


if __name__ == "__main__":
    unittest.main()
