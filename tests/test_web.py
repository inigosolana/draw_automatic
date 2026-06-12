from pathlib import Path
from io import BytesIO
import unittest

from generator.glpi_client import GlpiClient, build_customer_catalog
from generator.knowledge_base import learn_from_drawio, load_learned_items
from generator.web_adapter import build_drawio_from_data, form_to_data, form_to_structured_data, resolve_library_path
from web_app import DOWNLOADS, create_app


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = str(ROOT / "tests" / "fixtures" / "test_library.xml")


class WebAdapterTests(unittest.TestCase):
    def test_glpi_entities_are_loaded_in_pages(self) -> None:
        client = GlpiClient("http://glpi.test/apirest.php", "app", "user")
        calls = []

        class FakeSession:
            def __enter__(self):
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        client.session = lambda: FakeSession()

        def fake_request(path, headers, method="GET", payload=None):
            calls.append(path)
            if "range=0-999" in path:
                return {"value": [{"id": index} for index in range(1000)]}
            return {"value": [{"id": 1000}]}

        client._request = fake_request
        entities = client.list_entities()
        self.assertEqual(len(entities), 1001)
        self.assertIn("range=1000-1999", calls[1])

    def test_knowledge_base_learns_labeled_image(self) -> None:
        from tempfile import TemporaryDirectory

        xml = (
            '<mxfile><diagram><mxGraphModel><root>'
            '<mxCell id="1" vertex="1" style="shape=image;image=data:image/png;base64,ABC">'
            '<mxGeometry x="10" y="10" width="120" height="120" as="geometry"/></mxCell>'
            '<mxCell id="2" value="PANASONIC KX" vertex="1">'
            '<mxGeometry x="10" y="150" width="120" height="30" as="geometry"/></mxCell>'
            '</root></mxGraphModel></diagram></mxfile>'
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            added = learn_from_drawio(xml, "old.drawio", path)
            self.assertEqual(added, ["PANASONIC KX"])
            self.assertEqual(load_learned_items(path)[0]["source"], "old.drawio")

    def test_glpi_diagram_payload_targets_selected_entity(self) -> None:
        client = GlpiClient("http://glpi.test/apirest.php", "app", "user")
        calls = []

        class FakeSession:
            def __enter__(self):
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        client.session = lambda: FakeSession()

        def fake_request(path, headers, method="GET", payload=None):
            calls.append((path, method, payload))
            return {"id": 42 if path == "PluginArchimapGraph" else 84}

        client._request = fake_request
        diagram_id = client.create_network_diagram(7, "Cliente - Sede", "Diagrama", "<mxfile />")

        self.assertEqual(diagram_id, 42)
        self.assertEqual(calls[0][0], "PluginArchimapGraph")
        self.assertEqual(calls[0][1], "POST")
        self.assertEqual(calls[0][2]["input"]["entities_id"], 7)
        self.assertEqual(calls[0][2]["input"]["graph"], "%3Cmxfile%20%2F%3E")
        self.assertEqual(calls[1][0], "PluginArchimapGraph_Item")
        self.assertEqual(calls[1][2]["input"]["itemtype"], "Entity")
        self.assertEqual(calls[1][2]["input"]["items_id"], 7)

    def test_glpi_diagram_url_points_to_archimap(self) -> None:
        client = GlpiClient("https://glpi.example/apirest.php", "app", "user")
        self.assertEqual(
            client.diagram_url(2265),
            "https://glpi.example/marketplace/archimap/front/graph.form.php?id=2265",
        )

    def test_glpi_catalog_groups_sites_under_customer(self) -> None:
        catalog = build_customer_catalog(
            [
                {"id": 0, "name": "AUSARTA", "level": 1, "entities_id": None},
                {"id": 1, "name": "Cantabria", "level": 2, "entities_id": 0},
                {"id": 2, "name": "Q3968003H - IES CANTABRIA", "level": 3, "entities_id": 1},
                {
                    "id": 3,
                    "name": "Bilbao",
                    "level": 4,
                    "entities_id": 2,
                    "address": "Gran Via 1",
                    "town": "Bilbao",
                },
            ]
        )
        self.assertEqual(catalog[0]["nombre"], "Cantabria")
        customer = catalog[0]["clientes"][0]
        self.assertEqual(customer["nombre"], "IES CANTABRIA")
        self.assertEqual(customer["cif"], "Q3968003H")
        self.assertEqual(customer["sedes"][0]["nombre"], "Bilbao")
        self.assertEqual(customer["sedes"][0]["direccion"], "Gran Via 1, Bilbao")

    def test_form_builds_strict_structured_json(self) -> None:
        structured = form_to_structured_data(
            {
                "cliente": "Cliente Demo",
                "cif": "B123",
                "direccion": "Calle Mayor 1",
                "internet_tipo": "Fibra",
                "internet_velocidad": "600Mb",
                "internet_proveedor": "SARENET",
                "ont_modelo": "ONT ZTE",
                "router_modelo": "CHATEAU",
                "router_ip": "192.168.1.1/24",
                "equipos_text": "* 3 telefonos Fanvil V62",
                "terminal_details": (
                    "101 | SN1 | AA:BB:CC:DD:EE:01\n"
                    "102 | SN2 | AA:BB:CC:DD:EE:02\n"
                    "103 | |"
                ),
            }
        )
        site = structured["sedes"][0]
        self.assertEqual(site["nombre"], "Sede Principal")
        self.assertEqual(site["equipos"][0]["tipo"], "router")
        self.assertEqual(site["equipos"][0]["ip"], "192.168.1.1/24")
        self.assertEqual(site["conectividad"]["proveedor"], "SARENET")
        phones = site["equipos"][1:]
        self.assertEqual([phone["extension"] for phone in phones], ["101", "102", "103"])
        self.assertEqual([phone["cantidad"] for phone in phones], [1, 1, 1])
        self.assertNotIn("serial_number", phones[2])
        self.assertNotIn("mac", phones[2])
        self.assertTrue(all(phone["tipo"] == "telefono" for phone in phones))

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
            "terminal_details": "2001 | SN1 | AA:BB:CC:DD:EE:01",
        }
        data = form_to_data(form)
        self.assertEqual(data["cliente"], "Cliente Demo")
        self.assertEqual(data["router"]["ip"], "192.168.1.1/24")
        self.assertEqual(len(data["equipos"]), 3)
        self.assertEqual(data["template"], "con_switch")
        self.assertEqual(data["equipos"][0]["serial_number"], "SN1")

    def test_owned_and_external_devices_use_green_and_red_labels(self) -> None:
        data = form_to_data(
            {
                "cliente": "Cliente Demo",
                "sede": "Sede 1",
                "direccion": "Calle Mayor 1",
                "router_modelo": "CHATEAU",
                "equipos_text": "* 1 Fanvil V62 propio\n* 1 T-31 ajeno",
            }
        )
        generated = build_drawio_from_data(data, LIBRARY)
        self.assertIn("fontColor=#008000", generated.result.xml)
        self.assertIn("fontColor=#d00000", generated.result.xml)

    def test_build_drawio_from_data_generates_filename(self) -> None:
        data = form_to_data(
            {
                "cliente": "Pescados Gines e Hijos",
                "sede": "Esnabide 18",
                "direccion": "Pasaia",
                "ont_modelo": "ONT ZTE",
                "router_modelo": "CHATEAU",
                "router_ip": "192.168.0.1/24",
            }
        )
        generated = build_drawio_from_data(data, LIBRARY)
        self.assertTrue(generated.filename.endswith(".drawio"))
        self.assertIn("<mxfile", generated.result.xml)
        self.assertIn("LAN 192.168.0.1/24", generated.result.xml)

    def test_resolve_library_path_checks_project_parent(self) -> None:
        resolved = resolve_library_path("tests/fixtures/test_library.xml")
        self.assertEqual(resolved.resolve(), (ROOT / "tests" / "fixtures" / "test_library.xml").resolve())

    def test_real_library_loads_custom_w71h_icon(self) -> None:
        real_library = ROOT.parent / "libreria_Ausarta_JUN_2026.xml"
        if not real_library.exists():
            self.skipTest("La libreria real no esta disponible en este entorno.")
        generated = build_drawio_from_data(
            form_to_data(
                {
                    "cliente": "Demo",
                    "sede": "Central",
                    "direccion": "Bilbao",
                    "ont_modelo": "ONT ZTE",
                    "router_modelo": "CHATEAU",
                    "equipos_text": "* 1 W71H",
                }
            ),
            real_library,
        )
        self.assertNotIn("No se ha encontrado icono para: W71H", generated.result.warnings)


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

    def test_upload_draw_rejects_invalid_xml(self) -> None:
        response = self.client.post(
            "/upload-draw",
            data={
                "glpi_entity_id": "7",
                "glpi_cliente": "Cliente",
                "glpi_sede": "Sede",
                "drawio_file": (BytesIO(b"not xml"), "antiguo.drawio"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No se ha podido subir el diagrama", response.data)

    def test_upload_draw_page_is_available(self) -> None:
        response = self.client.get("/upload-draw")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Subir draw antiguo a GLPI", response.data)


if __name__ == "__main__":
    unittest.main()
