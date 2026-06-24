import os

os.environ.setdefault("DRAWIO_ADMIN_USERS", "test admin,admin user")
os.environ.setdefault("DRAWIO_SECRET_KEY", "pytest-secret-key-not-for-production")
