import os
import ssl
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

from generator.glpi_client import GlpiClient, GlpiEndpoints, GlpiError


class GlpiClientRefactorTests(unittest.TestCase):
    def test_endpoints_build_paginated_paths(self) -> None:
        self.assertEqual(
            GlpiEndpoints.entity_page(0, 1000),
            "Entity?range=0-999&with_inheritance=true",
        )
        self.assertEqual(
            GlpiEndpoints.archimap_graph_page(1000, 1000),
            "PluginArchimapGraph?range=1000-1999",
        )

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


if __name__ == "__main__":
    unittest.main()
