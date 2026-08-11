"""Fija el comportamiento de los helpers deduplicados en el refactor:
generator.geocode.parse_address y ZabbixClient.dominant_proxy."""
import unittest

from generator.geocode import parse_address
from generator.zabbix_client import ZabbixClient


class ParseAddressTests(unittest.TestCase):
    def test_recorta_sufijo_local_y_saca_variante_sin_numero(self):
        self.assertEqual(parse_address("Calle Mayor 12, bajo"),
                         ("Calle Mayor 12", "Calle Mayor"))

    def test_piso_y_numero(self):
        self.assertEqual(parse_address("Av. de la Constitución 3, 2 piso"),
                         ("Av. de la Constitución 3", "Av. de la Constitución"))

    def test_nave_sin_numero_de_portal(self):
        self.assertEqual(parse_address("Pol. Ind. Los Olivos, nave 4"),
                         ("Pol. Ind. Los Olivos", "Pol. Ind. Los Olivos"))

    def test_sin_numero_first_igual_nonum(self):
        self.assertEqual(parse_address("Gran Vía"), ("Gran Vía", "Gran Vía"))

    def test_vacio(self):
        self.assertEqual(parse_address(""), ("", ""))


class _FakeClient(ZabbixClient):
    def __init__(self, hosts):
        super().__init__("https://z/api", "tok")
        self._hosts = hosts
        self.calls = 0

    def _jsonrpc(self, method, params, request_id=1):
        self.calls += 1
        return self._hosts


class DominantProxyTests(unittest.TestCase):
    def test_devuelve_el_proxy_mas_usado(self):
        c = _FakeClient([{"proxyid": "10"}, {"proxyid": "10"}, {"proxyid": "7"}])
        self.assertEqual(c.dominant_proxy("55"), "10")

    def test_ignora_vacios_y_cero(self):
        c = _FakeClient([{"proxyid": "0"}, {"proxyid": ""}, {"proxyid": "9"}])
        self.assertEqual(c.dominant_proxy("55"), "9")

    def test_sin_hosts_devuelve_vacio(self):
        c = _FakeClient([])
        self.assertEqual(c.dominant_proxy("55"), "")

    def test_groupid_vacio_no_consulta(self):
        c = _FakeClient([{"proxyid": "9"}])
        self.assertEqual(c.dominant_proxy(""), "")
        self.assertEqual(c.calls, 0)

    def test_cachea_por_grupo(self):
        c = _FakeClient([{"proxyid": "9"}])
        c.dominant_proxy("55")
        c.dominant_proxy("55")
        self.assertEqual(c.calls, 1)  # segunda vez desde caché


if __name__ == "__main__":
    unittest.main()
