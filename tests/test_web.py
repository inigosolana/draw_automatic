from pathlib import Path
import unittest

from generator.web_adapter import build_drawio_from_data, form_to_data
from web_app import DOWNLOADS, create_app


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = str(ROOT / "tests" / "fixtures" / "test_library.xml")


class WebAdapterTests(unittest.TestCase):
    def test_form_to_data_converts_fields(self) -> None:
        form = {
            "cliente": "Cliente Demo",
            "cif": "B123",
            "sede": "Sede 1",
            "direccion": "Calle Mayor 1",
            "internet_tipo": "FTTH",
            "internet_velocidad": "1Gb",
            "ont_modelo": "ONT ZTE",
            "router_modelo": "MikroTik hAP ac2",
            "router_ip": "192.168.1.1/24",
            "equipos_text": "* 2 Fanvil V62, extensiones 2001 y 2002\n* 1 switch TP-Link 16P",
        }
        data = form_to_data(form)
        self.assertEqual(data["cliente"], "Cliente Demo")
        self.assertEqual(data["router"]["ip"], "192.168.1.1/24")
        self.assertEqual(len(data["equipos"]), 2)
        self.assertEqual(data["template"], "con_switch")

    def test_build_drawio_from_data_generates_filename(self) -> None:
        data = form_to_data(
            {
                "cliente": "Pescados Gines e Hijos",
                "sede": "Esnabide 18",
                "direccion": "Pasaia",
                "ont_modelo": "ONT ZTE",
                "router_modelo": "MikroTik hAP ac2",
            }
        )
        generated = build_drawio_from_data(data, LIBRARY)
        self.assertTrue(generated.filename.endswith(".drawio"))
        self.assertIn("<mxfile", generated.result.xml)


class WebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        DOWNLOADS.clear()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_post_generates_downloadable_drawio(self) -> None:
        response = self.client.post(
            "/generate",
            data={
                "cliente": "Cliente Demo",
                "sede": "Bilbao",
                "direccion": "Gran Via 1",
                "ont_modelo": "ONT ZTE",
                "router_modelo": "MikroTik hAP ac2",
                "library_path": LIBRARY,
                "equipos_text": "* 1 Fanvil V62, extension 2001",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Generacion completada", response.data)
        self.assertEqual(len(DOWNLOADS), 1)
        token = next(iter(DOWNLOADS))
        download = self.client.get(f"/download/{token}")
        self.assertEqual(download.status_code, 200)
        self.assertIn(b"<mxfile", download.data)
        self.assertIn(b"attachment;", download.headers["Content-Disposition"].encode())

    def test_post_fails_when_required_fields_are_missing(self) -> None:
        response = self.client.post(
            "/generate",
            data={"sede": "Bilbao", "library_path": LIBRARY},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"obligatorio", response.data)

    def test_post_fails_when_library_does_not_exist(self) -> None:
        response = self.client.post(
            "/generate",
            data={
                "cliente": "Cliente Demo",
                "sede": "Bilbao",
                "direccion": "Gran Via 1",
                "library_path": "missing_library.xml",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"No se ha encontrado la libreria", response.data)


if __name__ == "__main__":
    unittest.main()
