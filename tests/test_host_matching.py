"""Verifica el matcher IDF compartido (generator.host_matching) y que el alta web
sigue detectando correctamente si un cliente ya tiene host de fibra/backup."""
import unittest

from generator.host_matching import (
    DISTINCT,
    MATCH_MIN,
    build_idf_index,
    score_candidates,
    tokenize,
)


def _detect(cliente, host_names):
    """Réplica pura del núcleo de _existing_zabbix_hosts (sin Zabbix)."""
    routers = [h for h in host_names
               if h.upper().startswith(("FTTH", "FTHH", "BACKUP", "BACK_UP"))]
    inv, weight = build_idf_index([tokenize(n, drop_prov=True) for n in routers])
    ct = tokenize(cliente, drop_prov=True)
    out = {"fibra": "", "backup": ""}
    if not ct:
        return out
    scored = score_candidates(ct, inv, weight)
    for i in sorted(scored, key=lambda i: -scored[i][0]):
        namew, maxw = scored[i]
        if namew < MATCH_MIN or maxw < DISTINCT:
            break
        up = routers[i].upper()
        if not out["fibra"] and up.startswith(("FTTH", "FTHH")):
            out["fibra"] = routers[i]
        elif not out["backup"] and up.startswith(("BACKUP", "BACK_UP")):
            out["backup"] = routers[i]
    return out


class TokenizeTests(unittest.TestCase):
    def test_strips_accents_and_generics(self):
        # acentos fuera, genéricos ("SEDE","OFICINA") fuera, dígitos fuera
        self.assertEqual(
            tokenize("Fundación OFICINA CENTRAL Sede 2 Marañón"),
            {"FUNDACION", "MARANON"},
        )

    def test_drop_prov_removes_operator_prefixes(self):
        toks = tokenize("FTTH_AIRE_MARANON_SEDE1", drop_prov=True)
        self.assertIn("MARANON", toks)
        self.assertNotIn("FTTH", toks)
        self.assertNotIn("AIRE", toks)

    def test_min_len_three(self):
        # tokens de 2 letras (SL) fuera, de 3 dentro
        self.assertEqual(tokenize("IES SL"), {"IES"})


class DetectExistingTests(unittest.TestCase):
    # Los umbrales (MATCH_MIN=4.0/DISTINCT=3.0) están calibrados para el corpus
    # real (~3.800 hosts), donde un token único pesa log(3800/1)≈8.2. Rellenamos
    # con hosts basura para que los pesos IDF sean realistas.
    _FILLER = [f"FTTH_ADAMO_CLIENTEBASURA{i}_MUNI{i}" for i in range(400)]
    # "EXPRESS" aparece en muchos hosts → genérico de facto (peso IDF bajo).
    _FILLER += [f"FTTH_ORANGE_NEGOCIO_EXPRESS_LOCALIDAD{i}" for i in range(30)]
    HOSTS = [
        "FTTH_AIRE_FUNDACION_MARANON_SEDE1_SANTANDER_CALLE_MAYOR",
        "BACKUP_TELTONIKA_FUNDACION_MARANON_SEDE1_SANTANDER",
        "FTTH_ADAMO_PANADERIA_EXPRESS_BILBAO",
        "FTTH_SARENET_ACERALIA_GIJON",
    ] + _FILLER

    def test_detects_both_fibra_and_backup(self):
        r = _detect("FUNDACION MARAÑON", self.HOSTS)
        self.assertTrue(r["fibra"].startswith("FTTH_AIRE_FUNDACION_MARANON"))
        self.assertTrue(r["backup"].startswith("BACKUP_TELTONIKA_FUNDACION_MARANON"))

    def test_generic_word_is_no_false_positive(self):
        # "EXPRESS" es un genérico compartible; un cliente llamado solo "EXPRESS"
        # no debe emparejar (peso IDF insuficiente / sin token distintivo).
        r = _detect("EXPRESS", self.HOSTS)
        self.assertEqual(r, {"fibra": "", "backup": ""})

    def test_distinctive_single_token_matches(self):
        r = _detect("ACERALIA", self.HOSTS)
        self.assertTrue(r["fibra"].endswith("ACERALIA_GIJON"))
        self.assertEqual(r["backup"], "")

    def test_unknown_client_no_match(self):
        r = _detect("HOSPITAL DESCONOCIDO XYZ", self.HOSTS)
        self.assertEqual(r, {"fibra": "", "backup": ""})


if __name__ == "__main__":
    unittest.main()
