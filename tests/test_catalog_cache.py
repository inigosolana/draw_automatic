import tempfile
import unittest
from pathlib import Path

from generator.catalog_cache import CatalogCache


class CatalogCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = CatalogCache(Path(self._tmp.name) / "cache.sqlite3", ttl_seconds=300)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_round_trip_list(self) -> None:
        self.cache.set("catalog", [{"a": 1}])
        self.assertEqual(self.cache.get("catalog"), [{"a": 1}])

    def test_round_trip_dict(self) -> None:
        # admin_coverage is stored as a dict; get() must return it (regression).
        payload = {"missing_sites": 5, "provinces": [], "error": None}
        self.cache.set("admin_coverage", payload)
        self.assertEqual(self.cache.get("admin_coverage"), payload)

    def test_missing_key_returns_none(self) -> None:
        self.assertIsNone(self.cache.get("nope"))

    def test_corrupt_payload_returns_none(self) -> None:
        # Un payload que no es list/dict (p.ej. un número) no debe romper ni reusarse.
        self.cache.set("raro", 12345)  # type: ignore[arg-type]
        self.assertIsNone(self.cache.get("raro"))
        self.assertIsNone(self.cache.get("raro"))


if __name__ == "__main__":
    unittest.main()
