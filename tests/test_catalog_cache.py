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


if __name__ == "__main__":
    unittest.main()
