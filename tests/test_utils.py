import unittest

from generator.utils import dedupe_preserving_order, normalize_person_name, technician_is_admin

ADMIN_USERS = {
    "ana garcia",
    "garcia ana",
    "bob smith",
    "smith bob",
    "carol jones",
    "jones carol",
}


class DedupePreservingOrderTests(unittest.TestCase):
    def test_removes_duplicates_keeping_first_occurrence(self) -> None:
        self.assertEqual(
            dedupe_preserving_order(["2001", "2002", "2001", "2003", "2002"]),
            ["2001", "2002", "2003"],
        )

    def test_empty_and_unique(self) -> None:
        self.assertEqual(dedupe_preserving_order([]), [])
        self.assertEqual(dedupe_preserving_order(["a", "b"]), ["a", "b"])


class TechnicianLabelTests(unittest.TestCase):
    def test_prefers_name_then_username_then_default(self) -> None:
        from app_context import technician_label

        self.assertEqual(technician_label({"name": "Ana", "username": "ag"}), "Ana")
        self.assertEqual(technician_label({"username": "ag"}), "ag")
        self.assertEqual(technician_label({}), "desconocido")


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
