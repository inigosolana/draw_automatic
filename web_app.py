from app_context import DEFAULT_HOST, DEFAULT_PORT
from app_factory import create_app
from security_config import _production_requires_secret_key

if __name__ == "__main__":
    # Nunca activar el debugger de Werkzeug (RCE) en produccion. Se considera
    # produccion cuando DRAWIO_AUTH_REQUIRED=1 O DRAWIO_COOKIE_SECURE=1, el mismo
    # criterio que usa el resto del arranque (_production_requires_secret_key).
    debug = not _production_requires_secret_key()
    create_app().run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=debug)
