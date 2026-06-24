import os

from app_context import DEFAULT_HOST, DEFAULT_PORT
from app_factory import create_app

if __name__ == "__main__":
    local_dev = os.environ.get("DRAWIO_COOKIE_SECURE", "0") != "1"
    create_app().run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=local_dev)
