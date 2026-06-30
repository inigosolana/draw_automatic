import tempfile
import unittest
from pathlib import Path

from generator.connectivity_learning import ConnectivityLearning


def _payload(**kw):
    base = {
        "internet_tipo": "FIBRA",
        "internet_velocidad": "600",
        "internet_proveedor": "Telefonica",
        "ont_modelo": "ONT ZTE",
        "router_modelo": "hAP ac3",
        "backup_modelo": "",
        "router_ip": "192.168.1.1",
    }
    base.update(kw)
    return base


class ConnectivityLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.learning = ConnectivityLearning(Path(self.tmp.name) / "learning.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_suggestions_rank_by_frequency(self) -> None:
        for _ in range(3):
            self.learning.record(_payload(router_modelo="hAP ac3"))
        self.learning.record(_payload(router_modelo="CHATEAU"))
        sug = self.learning.suggestions()
        self.assertEqual(sug["router_modelo"][0], "hAP ac3")
        self.assertIn("CHATEAU", sug["router_modelo"])

    def test_suggestions_never_include_router_ip(self) -> None:
        self.learning.record(_payload())
        self.assertNotIn("router_ip", self.learning.suggestions())

    def test_empty_payload_not_recorded(self) -> None:
        self.learning.record({f: "" for f in ("internet_tipo", "internet_proveedor")})
        sug = self.learning.suggestions()
        self.assertEqual(sug["internet_tipo"], [])

    def test_context_provider_is_prioritised(self) -> None:
        # Movistar usa mucho un ONT; Telefonica otro.
        for _ in range(4):
            self.learning.record(_payload(internet_proveedor="Movistar", ont_modelo="ONT NOKIA"))
        for _ in range(2):
            self.learning.record(_payload(internet_proveedor="Telefonica", ont_modelo="ONT ZTE"))
        sug = self.learning.suggestions(proveedor="Telefonica")
        self.assertEqual(sug["ont_modelo"][0], "ONT ZTE")

    def test_correction_warning_after_threshold(self) -> None:
        for _ in range(3):
            self.learning.record_corrections(
                {"router_modelo": "hAP ac2"}, {"router_modelo": "hAP ac3"}
            )
        warns = self.learning.warnings(_payload(router_modelo="hAP ac2"))
        self.assertTrue(any("hAP ac3" in w for w in warns))

    def test_no_correction_warning_below_threshold(self) -> None:
        self.learning.record_corrections(
            {"router_modelo": "hAP ac2"}, {"router_modelo": "hAP ac3"}
        )
        warns = self.learning.warnings(_payload(router_modelo="hAP ac2"))
        self.assertEqual(warns, [])

    def test_combination_warning_for_unseen_pair(self) -> None:
        # 25+ observaciones, ambos valores vistos >=5 veces pero nunca juntos.
        for _ in range(15):
            self.learning.record(_payload(internet_proveedor="Telefonica", router_modelo="hAP ac3"))
        for _ in range(15):
            self.learning.record(_payload(internet_proveedor="Movistar", router_modelo="CHATEAU"))
        warns = self.learning.warnings(
            _payload(internet_proveedor="Telefonica", router_modelo="CHATEAU")
        )
        self.assertTrue(any("poco habitual" in w.lower() for w in warns))


if __name__ == "__main__":
    unittest.main()
