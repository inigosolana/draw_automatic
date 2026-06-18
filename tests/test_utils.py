import unittest

from generator.utils import normalize_person_name, technician_is_admin

ADMIN_USERS = {
    "iñigo solana",
    "solana iñigo",
    "alberto ferez",
    "ferez alberto",
    "marcos medina",
    "medina marcos",
}


class UtilsTests(unittest.TestCase):
    def test_normalize_person_name_ignores_surname_first_order(self) -> None:
        self.assertEqual(normalize_person_name("Solana Iñigo"), normalize_person_name("Iñigo Solana"))
        self.assertEqual(normalize_person_name("Ferez Alberto"), normalize_person_name("Alberto Ferez"))
        self.assertEqual(normalize_person_name("Medina Marcos"), normalize_person_name("Marcos Medina"))

    def test_normalize_person_name_handles_comma_format(self) -> None:
        self.assertEqual(normalize_person_name("Solana, Iñigo"), normalize_person_name("Iñigo Solana"))
        self.assertEqual(normalize_person_name("Ferez, Alberto"), normalize_person_name("Alberto Ferez"))
        self.assertEqual(normalize_person_name("Medina, Marcos"), normalize_person_name("Marcos Medina"))

    def test_technician_is_admin_for_all_authorized_users(self) -> None:
        cases = [
            {"name": "Solana Iñigo"},
            {"name": "Iñigo Solana"},
            {"name": "Ferez Alberto"},
            {"name": "Alberto Ferez"},
            {"name": "Medina Marcos"},
            {"name": "Marcos Medina"},
        ]
        for technician in cases:
            with self.subTest(technician=technician):
                self.assertTrue(technician_is_admin(technician, ADMIN_USERS))

    def test_technician_is_admin_rejects_unknown_user(self) -> None:
        self.assertFalse(technician_is_admin({"name": "Otro Usuario"}, ADMIN_USERS))


if __name__ == "__main__":
    unittest.main()
