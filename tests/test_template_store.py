import tempfile
import unittest
from pathlib import Path

from generator.template_store import TEMPLATE_FIELDS, TemplateStore


class TemplateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TemplateStore(Path(self.tmp.name) / "templates.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_save_and_get_roundtrip(self) -> None:
        payload = {f: f"v_{f}" for f in TEMPLATE_FIELDS}
        payload["campo_extra"] = "no se guarda"
        tid = self.store.save("Fibra + Backup", payload, "ana")
        got = self.store.get(tid)
        self.assertEqual(got["name"], "Fibra + Backup")
        self.assertNotIn("campo_extra", got["payload"])
        for f in TEMPLATE_FIELDS:
            self.assertEqual(got["payload"][f], f"v_{f}")

    def test_save_upserts_on_name(self) -> None:
        first = self.store.save("Solo 4G", {"router_modelo": "CHATEAU"}, "ana")
        second = self.store.save("Solo 4G", {"router_modelo": "OTRO"}, "luis")
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.list_all()), 1)
        self.assertEqual(self.store.get(first)["payload"]["router_modelo"], "OTRO")

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.store.save("   ", {"router_modelo": "X"}, "ana")

    def test_name_is_trimmed_and_capped(self) -> None:
        tid = self.store.save("  a   b  ", {}, "ana")
        self.assertEqual(self.store.get(tid)["name"], "a b")
        long_name = "x" * 200
        tid2 = self.store.save(long_name, {}, "ana")
        self.assertLessEqual(len(self.store.get(tid2)["name"]), 60)

    def test_delete(self) -> None:
        tid = self.store.save("Borrame", {}, "ana")
        self.store.delete(tid)
        self.assertIsNone(self.store.get(tid))
        self.assertEqual(self.store.list_all(), [])

    def test_list_all_sorted_by_name(self) -> None:
        self.store.save("Zeta", {}, "ana")
        self.store.save("alfa", {}, "ana")
        names = [t["name"] for t in self.store.list_all()]
        self.assertEqual(names, ["alfa", "Zeta"])


if __name__ == "__main__":
    unittest.main()
