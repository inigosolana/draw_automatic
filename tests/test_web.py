from pathlib import Path
from io import BytesIO
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from generator.catalog_cache import CatalogCache
from generator.diagram_activity import DiagramActivity
from generator.download_store import DownloadStore
from generator.glpi_client import GlpiClient, GlpiError, build_customer_catalog
from generator.knowledge_base import learn_from_drawio, load_learned_items
from generator.site_directory import SiteDirectory, apply_saved_addresses
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

    def test_glpi_diagrams_can_be_filtered_by_entity(self) -> None:
        client = GlpiClient("http://glpi.test/apirest.php", "app", "user")

        class FakeSession:
            def __enter__(self):
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        client.session = lambda: FakeSession()
        client._request = lambda *args, **kwargs: [
            {"id": 10, "entities_id": 7, "name": "Sede 7"},
            {"id": 11, "entities_id": 8, "name": "Sede 8"},
        ]
        diagrams = client.list_network_diagrams(7)
        self.assertEqual([diagram["id"] for diagram in diagrams], [10])

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

    def test_glpi_diagram_uses_single_session(self) -> None:
        client = GlpiClient("http://glpi.test/apirest.php", "app", "user")
        sessions = []

        class FakeSession:
            def __enter__(self):
                sessions.append("open")
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                sessions.append("close")
                return False

        client.session = lambda: FakeSession()
        client._request = lambda path, headers, method="GET", payload=None: {
            "id": 42 if path == "PluginArchimapGraph" else 84
        }
        client.create_network_diagram(7, "Cliente", "Diagrama", "<mxfile />")
        self.assertEqual(sessions, ["open", "close"])

    def test_glpi_user_authentication_returns_technician_without_password(self) -> None:
        client = GlpiClient("http://glpi.test/apirest.php", "app", "service")
        calls = []

        def fake_request(path, headers, method="GET", payload=None):
            calls.append((path, headers))
            if path == "initSession":
                return {"session_token": "user-session"}
            if path == "getFullSession":
                return {"session": {"glpiID": 25, "glpiname": "tecnico", "glpifriendlyname": "Técnico Uno"}}
            return {}

        client._request = fake_request
        identity = client.authenticate_user("tecnico", "secreto")
        self.assertEqual(identity["id"], 25)
        self.assertEqual(identity["name"], "Técnico Uno")
        self.assertNotIn("password", identity)
        self.assertTrue(calls[0][1]["Authorization"].startswith("Basic "))

    def test_glpi_session_failure_has_clear_error(self) -> None:
        client = GlpiClient("http://glpi.test/apirest.php", "app", "user")
        client._request = lambda *args, **kwargs: {}
        with self.assertRaisesRegex(GlpiError, "token de sesion"):
            with client.session():
                pass

    def test_glpi_timeout_is_wrapped(self) -> None:
        client = GlpiClient("http://glpi.test/apirest.php", "app", "user")
        with patch("generator.glpi_client.urlopen", side_effect=URLError("timeout")):
            with self.assertRaisesRegex(GlpiError, "No se ha podido consultar GLPI"):
                client._request("initSession", {})

    def test_glpi_invalid_entity_response_is_wrapped(self) -> None:
        client = GlpiClient("http://glpi.test/apirest.php", "app", "user")
        error = HTTPError(
            "http://glpi.test/apirest.php/PluginArchimapGraph",
            400,
            "Bad Request",
            {},
            BytesIO(b'["ERROR_ITEM_NOT_FOUND","Entidad invalida"]'),
        )
        with patch("generator.glpi_client.urlopen", side_effect=error):
            with self.assertRaisesRegex(GlpiError, "GLPI ha rechazado la operacion \\(400\\)"):
                client._request("PluginArchimapGraph", {}, method="POST", payload={"input": {}})

    def test_download_store_removes_expired_entries(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            store = DownloadStore(Path(directory) / "downloads.sqlite3", ttl_seconds=1)
            store["token"] = {"xml": "<mxfile />"}
            self.assertEqual(len(store), 1)
            connection = store._connect()
            try:
                with connection:
                    connection.execute("UPDATE downloads SET expires_at = ?", (time.time() - 1,))
            finally:
                connection.close()
            self.assertEqual(len(store), 0)
            self.assertIsNone(store.get("token"))

    def test_catalog_cache_is_shared_and_expires(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            writer = CatalogCache(path, ttl_seconds=1)
            reader = CatalogCache(path, ttl_seconds=1)
            catalog = [{"nombre": "Vizcaya", "clientes": []}]

            writer.set("glpi_customer_catalog", catalog)
            self.assertEqual(reader.get("glpi_customer_catalog"), catalog)

            with patch("generator.catalog_cache.time.time", return_value=time.time() + 2):
                self.assertIsNone(reader.get("glpi_customer_catalog"))

    def test_diagram_activity_is_filtered_by_technician(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            activity = DiagramActivity(Path(directory) / "activity.sqlite3")
            activity.add(
                diagram_id=101,
                entity_id=7,
                diagram_name="Cliente - Sede",
                client_name="Cliente",
                site_name="Sede",
                technician={"username": "tecnico.uno", "name": "Tecnico Uno"},
                source="Generado",
            )
            activity.add(
                diagram_id=102,
                entity_id=8,
                diagram_name="Otro - Sede",
                client_name="Otro",
                site_name="Sede",
                technician={"username": "tecnico.dos", "name": "Tecnico Dos"},
                source="Archivo antiguo",
            )

            rows = activity.list_for_technician("tecnico.uno")
            self.assertEqual([row["diagram_id"] for row in rows], [101])

    def test_site_address_is_persisted_by_entity_id(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            sites = SiteDirectory(Path(directory) / "sites.sqlite3")
            sites.set(45, "AVENIDA LIBERTAD, 65, 5. BARAKALDO 48901, Bizkaia", "Tecnico Uno")
            saved = sites.get(45)
            self.assertEqual(saved["address"], "AVENIDA LIBERTAD, 65, 5. BARAKALDO 48901, Bizkaia")
            self.assertEqual(saved["updated_by"], "Tecnico Uno")

    def test_saved_address_overrides_incomplete_glpi_address(self) -> None:
        catalog = [
            {
                "clientes": [
                    {
                        "sedes": [
                            {"id": 45, "nombre": "Matriz", "direccion": "BARAKALDO, 48901, Bizkaia"}
                        ]
                    }
                ]
            }
        ]
        result = apply_saved_addresses(
            catalog,
            {45: {"address": "AVENIDA LIBERTAD, 65, BARAKALDO", "updated_by": "Tecnico", "updated_at": 1}},
        )
        site = result[0]["clientes"][0]["sedes"][0]
        self.assertEqual(site["direccion"], "AVENIDA LIBERTAD, 65, BARAKALDO")
        self.assertTrue(site["direccion_guardada"])
        self.assertEqual(site["direccion_glpi"], "BARAKALDO, 48901, Bizkaia")

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

    def test_chateau_discards_external_backup_device(self) -> None:
        data = form_to_data(
            {
                "cliente": "Cliente Demo",
                "sede": "Sede 1",
                "direccion": "Calle Mayor 1",
                "internet_tipo": "FIBRA + BACK UP",
                "router_modelo": "CHATEAU",
                "backup_modelo": "WAP LTE",
            }
        )

        self.assertEqual(data["internet"]["backup"], "")

    def test_terminal_rows_add_equipment_and_details(self) -> None:
        data = form_to_data(
            {
                "cliente": "Cliente Demo",
                "sede": "Sede 1",
                "direccion": "Calle Mayor 1",
                "router_modelo": "CHATEAU",
                "terminal_equipment_text": (
                    "1 FANVIL V62, extension 2001 propio\n"
                    "1 T-31, extension 2002 ajeno"
                ),
                "terminal_details": (
                    "2001 | SN1 | AA:BB:CC:DD:EE:01 | propio\n"
                    "2002 | SN2 | AA:BB:CC:DD:EE:02 | ajeno"
                ),
            }
        )

        self.assertEqual(len(data["equipos"]), 2)
        self.assertEqual(data["equipos"][0]["serial_number"], "SN1")
        self.assertEqual(data["equipos"][1]["mac"], "AA:BB:CC:DD:EE:02")
        self.assertEqual(data["equipos"][1]["propiedad"], "ajeno")

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

    def test_device_catalog_includes_switch_models(self) -> None:
        from generator.device_catalog import SWITCH_MODELS, build_device_catalog

        catalog = build_device_catalog(str(ROOT / "tests" / "fixtures" / "test_library.xml"))
        switch_category = next(item for item in catalog if item["id"] == "switch")
        for model in SWITCH_MODELS:
            self.assertIn(model, switch_category["models"])
        otros = next(item for item in catalog if item["id"] == "otros")
        self.assertTrue(otros.get("custom"))

    def test_index_page_renders_device_picker(self) -> None:
        app = create_app()
        app.config["AUTH_REQUIRED"] = False
        client = app.test_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Dispositivos", body)
        self.assertIn("devices-json", body)
        self.assertIn("TP-Link 16P", body)

    def test_devices_json_populates_switch_and_custom_devices(self) -> None:
        import json

        payload = json.dumps(
            [
                {"category": "switch", "tipo": "switch", "modelo": "TP-Link 16P", "cantidad": 1, "propiedad": "propio"},
                {"category": "otros", "tipo": "otro", "modelo": "Servidor Dell", "cantidad": 1, "propiedad": "ajeno"},
            ]
        )
        data = form_to_data(
            {
                "cliente": "Demo",
                "sede": "Central",
                "direccion": "Bilbao",
                "ont_modelo": "ONT ZTE",
                "router_modelo": "CHATEAU",
                "devices_json": payload,
            }
        )
        switches = [item for item in data["equipos"] if item.get("tipo") == "switch"]
        others = [item for item in data["equipos"] if item.get("modelo") == "Servidor Dell"]
        self.assertEqual(len(switches), 1)
        self.assertIn("switch", switches[0]["modelo"].lower())
        self.assertEqual(others[0]["propiedad"], "ajeno")

    def test_monitored_4g_uses_capacity_instead_of_speed(self) -> None:
        data = form_to_data(
            {
                "cliente": "Demo",
                "sede": "Central",
                "direccion": "Bilbao",
                "internet_tipo": "SOLO 4G MONITORIZADO",
                "internet_velocidad": "400 GB",
                "internet_proveedor": "Movistar",
                "ont_modelo": "ONT ZTE",
                "router_modelo": "CHATEAU",
            }
        )
        self.assertEqual(data["internet"]["capacidad"], "400 GB")
        self.assertEqual(data["internet"]["velocidad"], "")
        generated = build_drawio_from_data(data, LIBRARY)
        self.assertIn("400 GB", generated.result.xml)
        self.assertIn("Movistar", generated.result.xml)

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

    def test_resolve_library_path_falls_back_when_mount_is_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broken_mount = Path(directory) / "libreria_Ausarta_JUN_2026.xml"
            broken_mount.mkdir()
            resolved = resolve_library_path(broken_mount)
            self.assertTrue(resolved.is_file())
            self.assertEqual(resolved.name, "libreria_Ausarta_JUN_2026.xml")

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

    def test_health_endpoint_is_available(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_diagram_query_page_is_available(self) -> None:
        with patch("web_app.GlpiClient.from_environment", return_value=None):
            response = self.client.get("/diagrams")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Consultar diagramas publicados", response.data)

    def test_my_diagrams_page_uses_authenticated_technician(self) -> None:
        self.app.config["AUTH_REQUIRED"] = True
        with self.client.session_transaction() as browser_session:
            browser_session["technician"] = {
                "username": "tecnico.uno",
                "name": "Tecnico Uno",
            }
        rows = [
            {
                "diagram_id": 101,
                "entity_id": 7,
                "diagram_name": "Cliente - Sede",
                "client_name": "Cliente",
                "site_name": "Sede",
                "technician_name": "Tecnico Uno",
                "source": "Generado",
                "created_at": time.time(),
            }
        ]
        with patch("web_app.ACTIVITY.list_for_technician", return_value=rows) as list_activity:
            with patch("web_app.GlpiClient.from_environment", return_value=None):
                response = self.client.get("/my-diagrams")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mis diagramas", response.data)
        self.assertIn(b"Cliente - Sede", response.data)
        list_activity.assert_called_once_with("tecnico.uno")

    def test_authentication_redirects_to_login_when_enabled(self) -> None:
        self.app.config["AUTH_REQUIRED"] = True
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_glpi_login_stores_technician_identity(self) -> None:
        self.app.config["AUTH_REQUIRED"] = True
        configured_client = GlpiClient("http://glpi", "app", "service")
        configured_client.authenticate_user = lambda username, password: {
            "id": 7,
            "username": username,
            "name": "Tecnico Prueba",
        }
        with patch("web_app.GlpiClient.from_environment", return_value=configured_client):
            response = self.client.post(
                "/login",
                data={"username": "tecnico", "password": "clave"},
            )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as browser_session:
            self.assertEqual(browser_session["technician"]["name"], "Tecnico Prueba")

    def test_login_allows_browser_password_managers(self) -> None:
        response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'autocomplete="on"', response.data)
        self.assertIn(b'autocomplete="username"', response.data)
        self.assertIn(b'autocomplete="current-password"', response.data)

    def test_preview_page_loads_pending_diagram(self) -> None:
        DOWNLOADS["preview-token"] = {
            "filename": "demo.drawio",
            "xml": "<mxfile />",
            "entity_id": "",
            "cliente": "Demo",
            "sede": "Central",
            "uploaded": False,
        }
        response = self.client.get("/preview/preview-token")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Previsualizaci", response.data)
        self.assertIn(b"embed.diagrams.net", response.data)

    def test_confirm_blocks_duplicate_diagram_without_override(self) -> None:
        DOWNLOADS["duplicate-token"] = {
            "filename": "demo.drawio",
            "xml": "<mxfile />",
            "entity_id": 7,
            "cliente": "Demo",
            "sede": "Central",
            "uploaded": False,
            "technician": {"username": "tech", "name": "Tecnico Uno"},
        }
        configured_client = GlpiClient("http://glpi", "a", "u")
        configured_client.list_network_diagrams = lambda entity_id: [{"id": 99, "entities_id": entity_id}]
        with patch("web_app.GlpiClient.from_environment", return_value=configured_client):
            response = self.client.post("/confirm-glpi/duplicate-token")
        self.assertEqual(response.status_code, 409)
        self.assertIn(b"ya tiene un diagrama", response.data)

    def test_post_fails_when_required_fields_are_missing(self) -> None:
        response = self.client.post(
            "/generate",
            data={"sede": "Bilbao", "library_path": LIBRARY},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"obligatorio", response.data)

    def test_post_fails_when_library_does_not_exist(self) -> None:
        with patch("generator.web_adapter.BUNDLED_LIBRARY", Path("/missing/bundled.xml")):
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

    def test_upload_draw_rejects_dtd_and_external_entity(self) -> None:
        dangerous_xml = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE mxfile [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            b"<mxfile><diagram>&xxe;</diagram></mxfile>"
        )
        response = self.client.post(
            "/upload-draw",
            data={
                "glpi_entity_id": "7",
                "glpi_cliente": "Cliente",
                "glpi_sede": "Sede",
                "drawio_file": (BytesIO(dangerous_xml), "peligroso.drawio"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No se ha podido subir el diagrama", response.data)

    def test_generate_rejects_invalid_glpi_entity_id(self) -> None:
        response = self.client.post(
            "/generate",
            data={
                "cliente": "Cliente Demo",
                "sede": "Bilbao",
                "direccion": "Gran Via 1",
                "ont_modelo": "ONT ZTE",
                "router_modelo": "MikroTik hAP ac2",
                "library_path": LIBRARY,
                "glpi_entity_id": "sede-7",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"ID entero positivo", response.data)

    def test_confirm_rejects_invalid_persisted_entity_id(self) -> None:
        DOWNLOADS["invalid-id"] = {
            "filename": "demo.drawio",
            "xml": "<mxfile />",
            "entity_id": "not-an-id",
            "cliente": "Demo",
            "sede": "Central",
            "uploaded": False,
        }
        configured_client = GlpiClient("http://glpi", "a", "u")
        with patch("web_app.GlpiClient.from_environment", return_value=configured_client):
            response = self.client.post("/confirm-glpi/invalid-id")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"ID entero positivo", response.data)


if __name__ == "__main__":
    unittest.main()
