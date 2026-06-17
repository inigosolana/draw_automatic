import unittest

from generator.safe_errors import public_error_message


class SafeErrorsTests(unittest.TestCase):
    def test_hides_password_related_text(self) -> None:
        message = public_error_message("Invalid password for user admin", context="login")
        self.assertNotIn("password", message.lower())
        self.assertIn("login", message.lower())

    def test_hides_api_tokens(self) -> None:
        message = public_error_message('{"session_token":"abc123"}', context="consulta")
        self.assertNotIn("abc123", message)
        self.assertNotIn("session_token", message)

    def test_allows_short_glpi_status_messages(self) -> None:
        message = public_error_message("No se ha podido conectar con GLPI.", context="carga")
        self.assertIn("GLPI", message)


if __name__ == "__main__":
    unittest.main()
