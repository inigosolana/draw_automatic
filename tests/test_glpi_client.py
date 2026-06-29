import os
import ssl
import unittest
from urllib.parse import quote
from unittest.mock import MagicMock, patch

from generator.glpi_client import GlpiClient, GlpiEndpoints, GlpiError


class GlpiClientRefactorTests(unittest.TestCase):
    def test_endpoints_build_paginated_paths(self) -> None:
        self.assertEqual(
            GlpiEndpoints.entity_page(0, 1000),
            "Entity?range=0-999&with_inheritance=true",
        )

    def test_archimap_search_page_uses_lightweight_fields(self) -> None:
        path = GlpiEndpoints.archimap_search_page(0, 200)
        self.assertTrue(path.startswith("search/PluginArchimapGraph?"))
        self.assertIn("range=0-199", path)
        self.assertIn("forcedisplay[0]=72", path)
        self.assertNotIn("criteria", path)

    def test_archimap_search_page_filters_by_entity(self) -> None:
        path = GlpiEndpoints.archimap_search_page(0, 200, entity_id=4189)
        self.assertIn("criteria[0][field]=81", path)
        self.assertIn("criteria[0][searchtype]=equals", path)
        self.assertIn("criteria[0][value]=4189", path)

    def test_batch_session_reuses_single_session(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user")
        calls: list[str] = []

        def fake_request(path, headers, method="GET", payload=None):
            calls.append(path)
            if path == GlpiEndpoints.INIT_SESSION:
                return {"session_token": "tok"}
            if path.startswith("search/"):
                return {"data": []}
            return {"id": 1}

        client._request = fake_request
        with client.batch_session():
            client.list_network_diagrams(5)
            client.list_network_diagrams(6)

        self.assertEqual(calls.count(GlpiEndpoints.INIT_SESSION), 1)
        self.assertEqual(calls.count(GlpiEndpoints.KILL_SESSION), 1)

    def test_without_batch_each_call_opens_session(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user")
        calls: list[str] = []

        def fake_request(path, headers, method="GET", payload=None):
            calls.append(path)
            if path == GlpiEndpoints.INIT_SESSION:
                return {"session_token": "tok"}
            return {"data": []}

        client._request = fake_request
        client.list_network_diagrams(5)
        client.list_network_diagrams(6)
        self.assertEqual(calls.count(GlpiEndpoints.INIT_SESSION), 2)

    def test_archimap_entities_page_only_requests_entity_field(self) -> None:
        path = GlpiEndpoints.archimap_entities_page(0, 500)
        self.assertEqual(
            path, "search/PluginArchimapGraph?range=0-499&forcedisplay[0]=81"
        )

    def test_list_covered_entity_ids_collects_unique_ints(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user")

        class FakeSession:
            def __enter__(self):
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        client.session = lambda: FakeSession()
        client._request = MagicMock(
            return_value={
                "data": [{"81": 10}, {"81": 10}, {"81": "25"}, {"81": None}]
            }
        )

        self.assertEqual(client.list_covered_entity_ids(), {10, 25})

    def test_list_network_diagrams_maps_search_rows(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user")

        class FakeSession:
            def __enter__(self):
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        client.session = lambda: FakeSession()
        client._request = MagicMock(
            return_value={
                "totalcount": 1,
                "data": [
                    {"72": 2279, "1": "Cliente - Sede", "2": "desc", "6": "Active", "81": 5583}
                ],
            }
        )

        diagrams = client.list_network_diagrams(entity_id=5583)

        self.assertEqual(len(diagrams), 1)
        self.assertEqual(diagrams[0]["id"], 2279)
        self.assertEqual(diagrams[0]["name"], "Cliente - Sede")
        self.assertEqual(diagrams[0]["entities_id"], 5583)
        path = client._request.call_args.args[0]
        self.assertTrue(path.startswith("search/PluginArchimapGraph?"))

    def test_from_environment_reads_verify_ssl_flag(self) -> None:
        env = {
            "GLPI_URL": "https://glpi.local/apirest.php",
            "GLPI_APP_TOKEN": "app",
            "GLPI_USER_TOKEN": "user",
            "GLPI_VERIFY_SSL": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            client = GlpiClient.from_environment()
        assert client is not None
        self.assertFalse(client.verify_ssl)

    def test_request_uses_unverified_ssl_context_when_disabled(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user", verify_ssl=False)
        response = MagicMock()
        response.read.return_value = b'{"session_token":"abc"}'
        response.__enter__.return_value = response

        with patch("generator.glpi_client.urlopen", return_value=response) as mock_urlopen:
            payload = client._request(GlpiEndpoints.INIT_SESSION, {})

        self.assertEqual(payload, {"session_token": "abc"})
        _, kwargs = mock_urlopen.call_args
        context = kwargs["context"]
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        self.assertFalse(context.check_hostname)

    def test_custom_ssl_context_overrides_verify_ssl(self) -> None:
        custom_context = ssl.create_default_context()
        client = GlpiClient(
            "https://glpi.test/apirest.php",
            "app",
            "user",
            verify_ssl=True,
            ssl_context=custom_context,
        )
        self.assertIs(client._urlopen_context(), custom_context)

    def test_request_uses_default_verification_when_enabled(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user", verify_ssl=True)
        response = MagicMock()
        response.read.return_value = b'{"ok": true}'
        response.__enter__.return_value = response

        with patch("generator.glpi_client.urlopen", return_value=response) as mock_urlopen:
            client._request(GlpiEndpoints.INIT_SESSION, {})

        _, kwargs = mock_urlopen.call_args
        self.assertIsNone(kwargs["context"])

    def test_get_network_diagram_xml_decodes_graph_payload(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user")
        encoded = quote("<mxfile><diagram /></mxfile>")

        class FakeSession:
            def __enter__(self):
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        client.session = lambda: FakeSession()
        client._request = MagicMock(
            return_value={
                "id": 2267,
                "name": "Cliente - Sede",
                "graph": encoded,
            }
        )

        xml, name = client.get_network_diagram_xml(2267)
        self.assertEqual(xml, "<mxfile><diagram /></mxfile>")
        self.assertEqual(name, "Cliente - Sede")

    def test_delete_network_diagram_calls_glpi_delete(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user")

        class FakeSession:
            def __enter__(self):
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        client.session = lambda: FakeSession()
        client._request = MagicMock(return_value=True)

        client.delete_network_diagram(2267)

        client._request.assert_called_once_with(
            "PluginArchimapGraph/2267",
            {"Session-Token": "session"},
            method="DELETE",
        )

    def test_save_network_diagram_version_updates_and_creates_copy(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user")
        diagram = {
            "id": 2267,
            "entities_id": 7,
            "name": "Cliente - Sede",
            "shortdescription": "Diagrama demo",
        }

        class FakeSession:
            def __enter__(self):
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        client.session = lambda: FakeSession()
        client.get_network_diagram = MagicMock(return_value=diagram)
        client.update_network_diagram_graph = MagicMock()
        client.create_network_diagram = MagicMock(return_value=9901)

        version_id, version_name = client.save_network_diagram_version(
            2267,
            "<mxfile><diagram /></mxfile>",
            technician={"name": "Ana", "username": "ana"},
        )

        self.assertEqual(version_id, 9901)
        self.assertRegex(version_name, r"^Cliente - Sede_\d{8}_\d{6}$")
        client.update_network_diagram_graph.assert_called_once_with(
            2267,
            "<mxfile><diagram /></mxfile>",
        )
        client.create_network_diagram.assert_called_once()
        create_kwargs = client.create_network_diagram.call_args.kwargs
        self.assertEqual(create_kwargs["entity_id"], 7)
        self.assertEqual(create_kwargs["name"], version_name)

    def test_update_network_diagram_graph_calls_glpi_put(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user")

        class FakeSession:
            def __enter__(self):
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        client.session = lambda: FakeSession()
        client._request = MagicMock(return_value={"id": 2267})

        client.update_network_diagram_graph(2267, "<mxfile><diagram /></mxfile>")

        client._request.assert_called_once()
        args, kwargs = client._request.call_args
        self.assertEqual(args[0], "PluginArchimapGraph/2267")
        self.assertEqual(kwargs["method"], "PUT")
        self.assertIn("graph", kwargs["payload"]["input"])

    def test_update_entity_address_calls_glpi_put(self) -> None:
        client = GlpiClient("https://glpi.test/apirest.php", "app", "user")

        class FakeSession:
            def __enter__(self):
                return {"Session-Token": "session"}

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        client.session = lambda: FakeSession()
        client._request = MagicMock(return_value={"id": 45})

        client.update_entity_address(45, "Calle Nueva, 5, Bilbao 48001, Bizkaia")

        client._request.assert_called_once()
        args, kwargs = client._request.call_args
        self.assertEqual(args[0], "Entity/45")
        self.assertEqual(kwargs["method"], "PUT")
        self.assertEqual(kwargs["payload"]["input"]["address"], "Calle Nueva, 5")


if __name__ == "__main__":
    unittest.main()
