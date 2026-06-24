import unittest

from generator.utils import normalize_person_name, technician_is_admin

ADMIN_USERS = {
    "ana garcia",
    "garcia ana",
    "bob smith",
    "smith bob",
    "carol jones",
    "jones carol",
}


class UtilsTests(unittest.TestCase):
    def test_normalize_person_name_ignores_surname_first_order(self) -> None:
        self.assertEqual(normalize_person_name("Garcia Ana"), normalize_person_name("Ana Garcia"))
        self.assertEqual(normalize_person_name("Smith Bob"), normalize_person_name("Bob Smith"))
        self.assertEqual(normalize_person_name("Jones Carol"), normalize_person_name("Carol Jones"))

    def test_normalize_person_name_handles_comma_format(self) -> None:
        self.assertEqual(normalize_person_name("Garcia, Ana"), normalize_person_name("Ana Garcia"))
        self.assertEqual(normalize_person_name("Smith, Bob"), normalize_person_name("Bob Smith"))
        self.assertEqual(normalize_person_name("Jones, Carol"), normalize_person_name("Carol Jones"))

    def test_technician_is_admin_for_all_authorized_users(self) -> None:
        cases = [
            {"name": "Garcia Ana"},
            {"name": "Ana Garcia"},
            {"name": "Smith Bob"},
            {"name": "Bob Smith"},
            {"name": "Jones Carol"},
            {"name": "Carol Jones"},
        ]
        for technician in cases:
            with self.subTest(technician=technician):
                self.assertTrue(technician_is_admin(technician, ADMIN_USERS))

    def test_technician_is_admin_rejects_unknown_user(self) -> None:
        self.assertFalse(technician_is_admin({"name": "Otro Usuario"}, ADMIN_USERS))


if __name__ == "__main__":
    unittest.main()
