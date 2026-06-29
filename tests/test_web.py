from pathlib import Path
from io import BytesIO
import os
import re
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from generator.catalog_cache import CatalogCache
from generator.diagram_activity import DiagramActivity
from generator.download_store import DownloadStore
from generator.glpi_client import GlpiClient, GlpiError, build_customer_catalog
from generator.knowledge_base import learn_from_drawio, load_learned_items
from generator.site_directory import SiteDirectory, apply_saved_addresses
from generator.web_adapter import build_drawio_from_data, form_to_data, form_to_structured_data, resolve_library_path
from app_factory import build_drawio_stores, create_app


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = str(ROOT / "tests" / "fixtures" / "test_library.xml")


def fake_glpi_client(**overrides):
    from contextlib import contextmanager

    client = GlpiClient("http://glpi.test/apirest.php", "app-token", "user-token")

    @contextmanager
    def _fake_session():
        yield {"Session-Token": "fake"}

    # Evita conexiones reales: session()/batch_session() sin red.
    client.session = _fake_session
    client.list_network_diagrams = lambda entity_id=None: []
    client.list_covered_entity_ids = lambda: set()
    client.create_network_diagram = lambda **kwargs: 42
    client.get_network_diagram = lambda diagram_id: {
        "id": diagram_id,
        "entities_id": 7,
        "name": "Cliente - Sede",
    }
    client.diagram_url = lambda diagram_id: f"http://glpi.test/diagram/{diagram_id}"
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


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
        # Formato de la search API: claves por numero de columna (72=id, 81=entities_id).
        client._request = lambda *args, **kwargs: {
            "data": [
                {"72": 10, "81": 7, "1": "Sede 7"},
                {"72": 11, "81": 8, "1": "Sede 8"},
            ]
        }
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
        with patch.dict(os.environ, {"GLPI_WEB_URL": ""}, clear=False):
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
        with self.assertRaisesRegex(GlpiError, "sesion de servicio"):
            with client.session():
                pass

    def test_glpi_timeout_is_wrapped(self) -> None:
        client = GlpiClient("http://glpi.test/apirest.php", "app", "user")
        with patch("generator.glpi_client.urlopen", side_effect=URLError("timeout")):
            with self.assertRaisesRegex(GlpiError, "No se ha podido conectar con GLPI"):
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
            with self.assertRaisesRegex(GlpiError, "GLPI ha rechazado la operacion \\(codigo 400\\)"):
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
            store.cleanup()
            self.assertEqual(len(store), 0)
            with self.assertRaises(KeyError):
                store["token"]

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
            self.assertEqual(saved["address"], "AVENIDA LIBERTAD, 65, 5")
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
        with patch.dict(os.environ, {"DRAWIO_RATELIMIT_STORAGE": "memory://"}, clear=False):
            app = create_app()
        app.config["AUTH_REQUIRED"] = False
        client = app.test_client()
        response = client.get("/draw")
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
        self.assertEqual(data["internet"]["backup"], "")
        self.assertEqual(data["ont"]["modelo"], "")
        self.assertEqual(data["router"]["modelo"], "CHATEAU")
        generated = build_drawio_from_data(data, LIBRARY)
        self.assertIn("400 GB", generated.result.xml)
        self.assertIn("Movistar", generated.result.xml)
        self.assertNotIn("ONT ZTE", generated.result.xml)

    def test_monitored_4g_forces_chateau_router(self) -> None:
        data = form_to_data(
            {
                "cliente": "Demo",
                "sede": "Central",
                "direccion": "Bilbao",
                "internet_tipo": "SOLO 4G MONITORIZADO",
                "internet_velocidad": "400 GB",
                "internet_proveedor": "Movistar",
                "router_modelo": "MikroTik hAP ac2",
            }
        )
        self.assertEqual(data["router"]["modelo"], "CHATEAU")

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
        real_library = ROOT.parent / "library" / "libreria_Ausarta_JUN_2026.xml"
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
        self._env_patch = patch.dict(os.environ, {"DRAWIO_RATELIMIT_STORAGE": "memory://"}, clear=False)
        self._env_patch.start()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.stores = build_drawio_stores(Path(self.temp_dir.name))
        self.app = create_app(self.stores)
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.app.config["AUTH_REQUIRED"] = False
        self.client = self.app.test_client()
        self.stores.downloads.clear()

    def tearDown(self) -> None:
        self._env_patch.stop()
        self.temp_dir.cleanup()

    def test_create_app_fails_without_secret_key_in_production(self) -> None:
        env = {
            "DRAWIO_AUTH_REQUIRED": "1",
            "DRAWIO_SECRET_KEY": "",
            "DRAWIO_RATELIMIT_STORAGE": "memory://",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(RuntimeError):
                create_app()

    def test_create_app_fails_with_placeholder_secret_key_when_cookie_secure(self) -> None:
        env = {
            "DRAWIO_AUTH_REQUIRED": "0",
            "DRAWIO_COOKIE_SECURE": "1",
            "DRAWIO_SECRET_KEY": "CAMBIAR_POR_UNA_CADENA_ALEATORIA_LARGA_GENERADA_CON_EL_COMANDO_ANTERIOR",
            "DRAWIO_RATELIMIT_STORAGE": "memory://",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(RuntimeError):
                create_app()

    def test_create_app_allows_ephemeral_secret_in_local_dev(self) -> None:
        env = {
            "DRAWIO_AUTH_REQUIRED": "0",
            "DRAWIO_COOKIE_SECURE": "0",
            "DRAWIO_SECRET_KEY": "",
            "DRAWIO_RATELIMIT_STORAGE": "memory://",
        }
        with patch.dict(os.environ, env, clear=False):
            app = create_app()
        self.assertTrue(app.config["SECRET_KEY"])

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
        self.assertEqual(len(self.stores.downloads), 1)
        token = next(iter(self.stores.downloads))
        download = self.client.get(f"/download/{token}")
        self.assertEqual(download.status_code, 200)
        self.assertIn(b"<mxfile", download.data)
        self.assertIn(b"attachment;", download.headers["Content-Disposition"].encode())

    def test_preview_returns_to_generation_screen_after_exit(self) -> None:
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
        token = next(iter(self.stores.downloads))
        self.assertIn(f"/preview/{token}?next=".encode(), response.data)
        preview_page = self.client.get(f"/preview/{token}?next=/draw%3Fpending%3D{token}")
        self.assertEqual(preview_page.status_code, 200)
        self.assertIn(f"/draw?pending={token}".encode(), preview_page.data)
        resume_page = self.client.get(f"/draw?pending={token}")
        self.assertEqual(resume_page.status_code, 200)
        self.assertIn(b"Generacion completada", resume_page.data)
        self.assertIn(b'data-download-mode="resume"', resume_page.data)
        self.assertIn(b"Cliente Demo", resume_page.data)

    def test_import_work_order_with_pasted_text(self) -> None:
        response = self.client.post(
            "/api/import-work-order",
            json={
                "pasted_text": "CIF\nB12345678\nNombre del cliente\nCliente Demo\nProducto: GPON ONT\nProducto: SIP-T31G",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["cif"], "B12345678")
        self.assertEqual(payload["cliente"], "Cliente Demo")
        self.assertEqual(payload["ont_modelo"], "ONT ZTE")

    def test_import_work_order_with_products_text(self) -> None:
        response = self.client.post(
            "/api/import-work-order",
            json={"products_text": "GPON ONT\nSIP-T31G\nCargador PSU"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["ont_modelo"], "ONT ZTE")
        self.assertEqual(payload["terminals"][0]["model"], "T-31")
        self.assertTrue(any("Cargador" in item for item in payload["warnings"]))

    @patch("generator.work_order_import.CrmClient.from_environment")
    def test_import_work_order_with_work_order_id_uses_crm_api(self, crm_factory) -> None:
        from generator.offer_mapper import ImportResult

        crm_factory.return_value.import_work_order.return_value = ImportResult(
            work_order_id="7885",
            cliente="Cliente CRM",
            cif="B12345678",
            sede="Central",
            direccion="Calle 1",
            internet_proveedor="AIRE",
            internet_velocidad="1 GB",
            glpi_entity_id="999",
            terminals=[{"model": "T-33", "extension": "3001", "serial": "SN1", "mac": "AA:BB", "ownership": "propio", "dect_base": ""}],
        )
        response = self.client.post("/api/import-work-order", json={"work_order_id": "7885"})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["work_order_id"], "7885")
        self.assertEqual(payload["cliente"], "Cliente CRM")
        self.assertEqual(payload["glpi_entity_id"], "999")
        self.assertEqual(payload["terminals"][0]["extension"], "3001")
        crm_factory.return_value.import_work_order.assert_called_once_with("7885")

    def test_health_endpoint_is_available(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_diagram_query_page_is_available(self) -> None:
        sample_catalog = [
            {
                "id": 1,
                "nombre": "Gipuzkoa",
                "clientes": [
                    {
                        "id": 2,
                        "nombre": "Cliente Demo",
                        "sedes": [{"id": 7, "nombre": "Central"}],
                    }
                ],
            }
        ]
        with patch("web.services.glpi_catalog.load_glpi_catalog", return_value=(sample_catalog, "")):
            response = self.client.get("/diagrams")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Consultar diagramas publicados", response.data)
        self.assertIn(b"diagram-province", response.data)
        self.assertIn(b"search-select", response.data)

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
        with patch.object(self.stores.activity, "list_for_technician", return_value=rows) as list_activity:
            with patch("web.blueprints.diagrams.GlpiClient.from_environment", return_value=fake_glpi_client()):
                response = self.client.get("/my-diagrams")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mis diagramas", response.data)
        self.assertIn(b"Cliente - Sede", response.data)
        self.assertIn(b"Previsualizar", response.data)
        self.assertIn(b"source-badge-generated", response.data)
        self.assertIn(b'data-source-filter="subido"', response.data)
        list_activity.assert_called_once_with("tecnico.uno")

    def test_admin_diagrams_lists_all_with_technician(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        rows = [
            {
                "diagram_id": 101,
                "entity_id": 7,
                "diagram_name": "Cliente A - Sede 1",
                "client_name": "Cliente A",
                "site_name": "Sede 1",
                "technician_username": "tecnico.uno",
                "technician_name": "Tecnico Uno",
                "source": "Generado",
                "created_at": time.time(),
            },
            {
                "diagram_id": 202,
                "entity_id": 8,
                "diagram_name": "Cliente B - Sede 2",
                "client_name": "Cliente B",
                "site_name": "Sede 2",
                "technician_username": "tecnico.dos",
                "technician_name": "Tecnico Dos",
                "source": "Draw subido",
                "created_at": time.time(),
            },
        ]
        with self.client.session_transaction() as browser_session:
            browser_session["technician"] = {
                "username": "admin.user",
                "name": "Admin User",
            }
        with patch("web.blueprints.admin.ADMIN_USERS", {"admin.user"}):
            with patch.object(self.stores.activity, "list_all", return_value=rows):
                with patch("web.blueprints.admin.GlpiClient.from_environment", return_value=fake_glpi_client()):
                    response = self.client.get("/admin/diagrams")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Todos los diagramas", response.data)
        self.assertIn(b"Tecnico Uno", response.data)
        self.assertIn(b"Tecnico Dos", response.data)
        self.assertIn(b"Cliente A", response.data)
        self.assertIn(b"Cliente B", response.data)
        self.assertIn(b"Borrar", response.data)

    def test_admin_diagrams_denies_non_admin(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        with self.client.session_transaction() as browser_session:
            browser_session["technician"] = {
                "username": "tecnico.uno",
                "name": "Tecnico Uno",
            }
        with patch("web.blueprints.admin.ADMIN_USERS", {"admin.user"}):
            response = self.client.get("/admin/diagrams")
        self.assertEqual(response.status_code, 403)

    def test_admin_delete_diagram_requires_admin(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        self.app.config["WTF_CSRF_ENABLED"] = False
        with self.client.session_transaction() as browser_session:
            browser_session["technician"] = {
                "username": "tecnico.uno",
                "name": "Tecnico Uno",
            }
        with patch("web.blueprints.admin.ADMIN_USERS", {"admin.user"}):
            response = self.client.post("/admin/diagrams/delete", data={"diagram_id": "101"})
        self.assertEqual(response.status_code, 403)

    def test_admin_delete_diagram_removes_from_glpi_and_activity(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        self.app.config["WTF_CSRF_ENABLED"] = False
        activity = self.stores.activity
        activity.add(
            diagram_id=101,
            entity_id=7,
            diagram_name="Cliente - Sede",
            client_name="Cliente",
            site_name="Sede",
            technician={"username": "tecnico.uno", "name": "Tecnico Uno"},
            source="Generado",
        )
        fake_client = fake_glpi_client()
        fake_client.delete_network_diagram = MagicMock()
        with self.client.session_transaction() as browser_session:
            browser_session["technician"] = {
                "username": "admin.user",
                "name": "Admin User",
            }
        with patch("web.blueprints.admin.ADMIN_USERS", {"admin.user"}):
            with patch("web.blueprints.admin.GlpiClient.from_environment", return_value=fake_client):
                response = self.client.post("/admin/diagrams/delete", data={"diagram_id": "101"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/diagrams?deleted=101", response.headers["Location"])
        fake_client.delete_network_diagram.assert_called_once_with(101)
        self.assertEqual(activity.list_for_technician("tecnico.uno"), [])

    def test_authentication_redirects_to_login_when_enabled(self) -> None:
        self.app.config["AUTH_REQUIRED"] = True
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_home_launcher_renders_app_cards(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Pasos tras la instalacion", body)
        self.assertIn("Paso 1", body)
        self.assertIn("Paso 2", body)
        self.assertIn("Paso 3", body)
        self.assertIn("Zabbix", body)
        self.assertIn("Passbolt", body)
        self.assertIn("Pronto", body)
        self.assertIn("proximamente", body)

    def test_zabbix_page_redirects_to_soon(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        with patch.dict(
            os.environ,
            {"ZABBIX_BASE_URL": "http://zabbix", "ZABBIX_API_TOKEN": "tok"},
            clear=False,
        ):
            response = self.client.get("/zabbix")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/zabbix-soon", response.headers["Location"])

    def test_zabbix_group_lookup_api(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        with patch.dict(
            os.environ,
            {"ZABBIX_BASE_URL": "http://zabbix", "ZABBIX_API_TOKEN": "tok"},
            clear=False,
        ):
            with patch(
                "web.blueprints.zabbix.ZabbixClient.resolve_host_group_for_province",
                return_value={"groupid": "15", "name": "Bizkaia"},
            ):
                response = self.client.get("/zabbix/api/group?provincia=Bizkaia")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["groupid"], "15")
        self.assertEqual(payload["name"], "Bizkaia")

    def test_glpi_login_stores_technician_identity(self) -> None:
        self.app.config["AUTH_REQUIRED"] = True
        configured_client = GlpiClient("http://glpi", "app", "service")
        configured_client.authenticate_user = lambda username, password: {
            "id": 7,
            "username": username,
            "name": "Tecnico Prueba",
        }
        with patch("web.services.glpi_catalog.GlpiClient.from_environment", return_value=configured_client):
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

    def test_preview_glpi_page_loads_archimap_diagram(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        fake_client = fake_glpi_client()
        fake_client.get_network_diagram_xml = lambda diagram_id: (
            "<mxfile><diagram /></mxfile>",
            "Cliente - Sede",
        )
        with patch("web.blueprints.diagrams.GlpiClient.from_environment", return_value=fake_client):
            response = self.client.get(
                "/preview/glpi/2267",
                headers={"X-Forwarded-Proto": "https", "Host": "draw.ausarta.net"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"preview-drawio.js", response.data)
        self.assertIn(b"Cliente - Sede", response.data)
        self.assertIn(b"Previsualizaci\xc3\xb3n editable", response.data)
        self.assertIn(b"saveUrl", response.data)
        self.assertIn(b"/preview/glpi/2267/save", response.data)
        self.assertIn(b"/preview/glpi/2267/xml", response.data)
        self.assertIn(b"embedUrl", response.data)
        self.assertIn(b"https://draw.ausarta.net/drawio-library.xml", response.data)
        iframe_pos = response.data.find(b'id="drawio-preview"')
        script_pos = response.data.find(b"preview-drawio.js")
        self.assertIn(b"preview-editor-shell", response.data)
        self.assertIn(b"preview-page-root", response.data)
        iframe_pos = response.data.find(b'id="drawio-preview"')
        script_pos = response.data.find(b"preview-drawio.js")
        self.assertGreater(script_pos, iframe_pos)
        self.assertIn(b"grid=0", response.data)
        self.assertNotIn(b"pv=0", response.data)

    def test_preview_glpi_xml_endpoint_returns_diagram(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        fake_client = fake_glpi_client()
        fake_client.get_network_diagram_xml = lambda diagram_id: (
            "<mxfile><diagram /></mxfile>",
            "Cliente - Sede",
        )
        with patch("web.blueprints.diagrams.GlpiClient.from_environment", return_value=fake_client):
            response = self.client.get("/preview/glpi/2267/xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<mxfile>", response.data)

    def test_preview_glpi_xml_endpoint_returns_404_when_missing(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        fake_client = fake_glpi_client()
        fake_client.get_network_diagram_xml = MagicMock(side_effect=GlpiError("Diagrama no encontrado."))
        with patch("web.blueprints.diagrams.GlpiClient.from_environment", return_value=fake_client):
            response = self.client.get("/preview/glpi/9999/xml")
        self.assertEqual(response.status_code, 404)

    def test_drawio_library_serves_xml_with_cors(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        response = self.client.get("/drawio-library.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<mxlibrary>", response.data)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://embed.diagrams.net",
        )
        gzip_response = self.client.get(
            "/drawio-library.xml",
            headers={"Accept-Encoding": "gzip"},
        )
        self.assertEqual(gzip_response.status_code, 200)
        self.assertEqual(gzip_response.headers.get("Content-Encoding"), "gzip")
        app_origin = self.client.get(
            "/drawio-library.xml",
            headers={"Origin": "https://app.diagrams.net"},
        )
        self.assertEqual(
            app_origin.headers.get("Access-Control-Allow-Origin"),
            "https://app.diagrams.net",
        )

    def test_preview_page_loads_pending_diagram(self) -> None:
        self.stores.downloads["preview-token"] = {
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
        self.assertIn(b"embedUrl", response.data)
        self.assertIn(b"configure=1", response.data)
        self.assertIn(b"libraryUrl", response.data)
        self.assertIn(b"/preview/preview-token/xml", response.data)
        self.assertIn(b"/preview/preview-token/save", response.data)
        self.assertIn(b"preview-drawio.js", response.data)
        self.assertIn(b"drawio-preview-config", response.data)
        self.assertNotIn(b"window.addEventListener", response.data)

    def test_preview_token_save_updates_pending_diagram(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.stores.downloads["preview-token"] = {
            "filename": "demo.drawio",
            "xml": "<mxfile />",
            "entity_id": "",
            "cliente": "Demo",
            "sede": "Central",
            "uploaded": False,
        }
        updated_xml = "<mxfile><diagram name='Page-1' /></mxfile>"
        response = self.client.post(
            "/preview/preview-token/save",
            json={"xml": updated_xml},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(self.stores.downloads["preview-token"]["xml"], updated_xml)

    def test_preview_glpi_save_updates_archimap(self) -> None:
        self.app.config["AUTH_REQUIRED"] = False
        self.app.config["WTF_CSRF_ENABLED"] = False
        fake_client = fake_glpi_client()
        fake_client.save_network_diagram_version = MagicMock(
            return_value=(9901, "Cliente - Sede_20260623_153045")
        )
        updated_xml = "<mxfile><diagram name='Page-1' /></mxfile>"
        with patch("web.blueprints.diagrams.GlpiClient.from_environment", return_value=fake_client):
            response = self.client.post(
                "/preview/glpi/2267/save",
                json={"xml": updated_xml},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version_name"], "Cliente - Sede_20260623_153045")
        fake_client.save_network_diagram_version.assert_called_once()
        args, kwargs = fake_client.save_network_diagram_version.call_args
        self.assertEqual(args[0], 2267)
        self.assertEqual(args[1], updated_xml)

    def test_preview_page_uses_csp_nonce_when_security_headers_enabled(self) -> None:
        env = {
            "DRAWIO_RATELIMIT_STORAGE": "memory://",
            "DRAWIO_COOKIE_SECURE": "1",
            "DRAWIO_ENABLE_SECURITY_HEADERS": "1",
            "DRAWIO_SECRET_KEY": "test-secret-key-for-csp-preview-page",
        }
        with patch.dict(os.environ, env, clear=False):
            app = create_app(self.stores)
            app.config["TESTING"] = True
            app.config["WTF_CSRF_ENABLED"] = False
            app.config["AUTH_REQUIRED"] = False
            client = app.test_client()
            self.stores.downloads["preview-token"] = {
                "filename": "demo.drawio",
                "xml": "<mxfile />",
                "entity_id": "",
                "cliente": "Demo",
                "sede": "Central",
                "uploaded": False,
            }
            response = client.get("/preview/preview-token")
        self.assertEqual(response.status_code, 200)
        csp = response.headers.get("Content-Security-Policy", "")
        self.assertIn("nonce-", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertRegex(response.data.decode("utf-8"), r'id="drawio-preview-config"\s+nonce="[^"]+"')

    def test_html_pages_do_not_use_executable_inline_scripts_under_csp(self) -> None:
        inline_script = re.compile(
            r'<script(?![^>]*\bsrc=)(?![^>]*type="application/json")[^>]*>',
            re.IGNORECASE,
        )
        env = {
            "DRAWIO_RATELIMIT_STORAGE": "memory://",
            "DRAWIO_COOKIE_SECURE": "1",
            "DRAWIO_ENABLE_SECURITY_HEADERS": "1",
            "DRAWIO_SECRET_KEY": "test-secret-key-for-csp-html-pages",
            "DRAWIO_ADMIN_USERS": "admin.user",
        }
        self.stores.downloads["preview-token"] = {
            "filename": "demo.drawio",
            "xml": "<mxfile />",
            "entity_id": "",
            "cliente": "Demo",
            "sede": "Central",
            "uploaded": False,
        }
        sample_catalog = [
            {
                "id": 1,
                "nombre": "Bizkaia",
                "clientes": [
                    {
                        "id": 10,
                        "nombre": "Cliente Demo",
                        "sedes": [{"id": 100, "nombre": "Sede 1"}],
                    }
                ],
            }
        ]

        with patch.dict(os.environ, env, clear=False):
            app = create_app(self.stores)
            app.config["TESTING"] = True
            app.config["WTF_CSRF_ENABLED"] = False
            app.config["AUTH_REQUIRED"] = False
            client = app.test_client()
            with patch("web.services.glpi_catalog.load_glpi_catalog", return_value=(sample_catalog, "")):
                with patch("web.services.glpi_catalog.GlpiClient.from_environment", return_value=None):
                    pages = [
                        client.get("/"),
                        client.get("/draw"),
                        client.get("/diagrams"),
                        client.get("/my-diagrams"),
                        client.get("/upload-draw"),
                        client.get("/preview/preview-token"),
                    ]
            with client.session_transaction() as browser_session:
                browser_session["technician"] = {
                    "username": "admin.user",
                    "name": "Admin User",
                }
            with patch("web.services.glpi_catalog.load_glpi_catalog", return_value=([], "")):
                with patch("web.services.glpi_catalog.GlpiClient.from_environment", return_value=None):
                    with patch("web.blueprints.admin.ADMIN_USERS", {"admin.user"}):
                        pages.append(client.get("/admin"))
                        pages.append(client.get("/admin/diagrams"))

        for response in pages:
            self.assertEqual(response.status_code, 200, response.request.path)
            html = response.data.decode("utf-8")
            self.assertIsNone(
                inline_script.search(html),
                f"Executable inline script found in {response.request.path}",
            )
            csp = response.headers.get("Content-Security-Policy", "")
            if "nonce-" not in csp:
                continue
            for tag in re.findall(r'<script type="application/json"[^>]*>', html):
                self.assertIn('nonce="', tag, msg=f"Missing nonce in JSON config on {response.request.path}")

    def test_confirm_blocks_duplicate_diagram_without_override(self) -> None:
        self.stores.downloads["duplicate-token"] = {
            "filename": "demo.drawio",
            "xml": "<mxfile />",
            "entity_id": 7,
            "cliente": "Demo",
            "sede": "Central",
            "uploaded": False,
            "technician": {"username": "tech", "name": "Tecnico Uno"},
        }
        configured_client = fake_glpi_client(
            list_network_diagrams=lambda entity_id: [{"id": 99, "entities_id": entity_id}],
        )
        with patch("web.services.glpi_catalog.GlpiClient.from_environment", return_value=configured_client):
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
        with patch("web.services.glpi_catalog.GlpiClient.from_environment", return_value=fake_glpi_client()):
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
        self.assertIn(b"No se ha podido completar la subida del diagrama", response.data)

    def test_upload_draw_page_is_available(self) -> None:
        response = self.client.get("/upload-draw")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Subir draw a GLPI", response.data)
        self.assertIn(b"Descargar clientes_con_sedes_sin_diagrama.xlsx", response.data)
        self.assertIn(b"Calle / direccion", response.data)

    def test_upload_draw_saves_corrected_address(self) -> None:
        sample_catalog = [
            {
                "id": 1,
                "nombre": "Bizkaia",
                "clientes": [
                    {
                        "id": 10,
                        "nombre": "Cliente Demo",
                        "sedes": [{"id": 7, "nombre": "Central", "direccion": "Calle Vieja 1"}],
                    }
                ],
            }
        ]
        valid_xml = b"<mxfile><diagram /></mxfile>"
        glpi_client = fake_glpi_client()
        glpi_client.update_entity_address = MagicMock()
        with patch("web.blueprints.glpi_import.load_glpi_catalog", return_value=(sample_catalog, "")):
            with patch("web.blueprints.glpi_import.GlpiClient.from_environment", return_value=glpi_client):
                response = self.client.post(
                    "/upload-draw",
                    data={
                        "glpi_entity_id": "7",
                        "glpi_cliente": "Cliente Demo",
                        "glpi_sede": "Central",
                        "glpi_direccion": "Calle Nueva 5",
                        "drawio_file": (BytesIO(valid_xml), "antiguo.drawio"),
                    },
                    content_type="multipart/form-data",
                )
        self.assertEqual(response.status_code, 200)
        saved = self.stores.sites.get(7)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["address"], "Calle Nueva 5")
        glpi_client.update_entity_address.assert_called_once_with(7, "Calle Nueva 5")

    def test_upload_draw_extracts_pdf_diagram(self) -> None:
        from urllib.parse import quote

        from pypdf import PdfWriter

        mxfile = '<mxfile><diagram name="P1">contenido</diagram></mxfile>'
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_metadata({"/Subject": quote(mxfile)})
        pdf_buffer = BytesIO()
        writer.write(pdf_buffer)
        pdf_buffer.seek(0)

        sample_catalog = [
            {
                "id": 1,
                "nombre": "Bizkaia",
                "clientes": [
                    {
                        "id": 10,
                        "nombre": "Cliente Demo",
                        "sedes": [{"id": 7, "nombre": "Central", "direccion": "Calle 1"}],
                    }
                ],
            }
        ]
        published: dict = {}
        glpi_client = fake_glpi_client(
            create_network_diagram=lambda **kwargs: published.update(kwargs) or 99
        )
        with patch("web.blueprints.glpi_import.load_glpi_catalog", return_value=(sample_catalog, "")):
            with patch("web.blueprints.glpi_import.GlpiClient.from_environment", return_value=glpi_client):
                response = self.client.post(
                    "/upload-draw",
                    data={
                        "glpi_entity_id": "7",
                        "glpi_cliente": "Cliente Demo",
                        "glpi_sede": "Central",
                        "drawio_files": (pdf_buffer, "cumcum_sede1.pdf"),
                    },
                    content_type="multipart/form-data",
                )
        self.assertEqual(response.status_code, 200)
        # El mxfile incrustado en el PDF se extrajo y se publicó como diagrama.
        self.assertEqual(published.get("graph_xml"), mxfile)
        self.assertIn(b"cumcum_sede1.pdf", response.data)

    def test_upload_draw_missing_sites_xlsx(self) -> None:
        sample_catalog = [
            {
                "id": 1,
                "nombre": "Bizkaia",
                "clientes": [
                    {
                        "id": 10,
                        "nombre": "Cliente Demo",
                        "sedes": [
                            {"id": 100, "nombre": "Sede 1", "direccion": "Calle 1"},
                            {"id": 101, "nombre": "Sede 2", "direccion": "Calle 2"},
                        ],
                    }
                ],
            }
        ]
        with patch("web.blueprints.glpi_import.load_glpi_catalog", return_value=(sample_catalog, "")):
            with patch(
                "web.blueprints.glpi_import.GlpiClient.from_environment",
                return_value=fake_glpi_client(
                    list_covered_entity_ids=lambda: {100},
                ),
            ):
                    response = self.client.get("/upload-draw/clientes_con_sedes_sin_diagrama.xlsx")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            response.content_type,
        )
        self.assertTrue(response.data.startswith(b"PK"))
        self.assertIn(
            b"clientes_con_sedes_sin_diagrama.xlsx",
            response.headers.get("Content-Disposition", "").encode(),
        )

    def test_upload_draw_site_diagrams_api(self) -> None:
        with patch("web.services.glpi_catalog.GlpiClient.from_environment", return_value=fake_glpi_client()):
            with patch(
                "web.blueprints.glpi_import.glpi_diagram_rows",
                return_value=[
                    {
                        "id": 12,
                        "name": "Cliente - Sede",
                        "created_label": "10/03/2026 09:15",
                        "technician": "Tecnico Uno",
                        "source": "Generado",
                        "url": "http://glpi/diagram/12",
                    }
                ],
            ):
                response = self.client.get("/upload-draw/site-diagrams?entity_id=7")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["diagrams"][0]["id"], 12)
        self.assertIn("/preview/glpi/12", payload["diagrams"][0]["preview_url"])

    def test_upload_draw_rejects_dtd_and_external_entity(self) -> None:
        dangerous_xml = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE mxfile [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            b"<mxfile><diagram>&xxe;</diagram></mxfile>"
        )
        with patch("web.services.glpi_catalog.GlpiClient.from_environment", return_value=fake_glpi_client()):
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
        self.assertIn(b"No se ha podido completar la subida del diagrama", response.data)

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
        self.stores.downloads["invalid-id"] = {
            "filename": "demo.drawio",
            "xml": "<mxfile />",
            "entity_id": "not-an-id",
            "cliente": "Demo",
            "sede": "Central",
            "uploaded": False,
        }
        configured_client = GlpiClient("http://glpi", "a", "u")
        with patch("web.services.glpi_catalog.GlpiClient.from_environment", return_value=configured_client):
            response = self.client.post("/confirm-glpi/invalid-id")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"No se ha podido completar la publicacion en GLPI", response.data)


if __name__ == "__main__":
    unittest.main()
