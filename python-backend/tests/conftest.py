import importlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def app_module(monkeypatch):
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    monkeypatch.setenv("RESTAURANT_DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")

    import app as _app_module
    importlib.reload(_app_module)
    _app_module.app.config["WTF_CSRF_ENABLED"] = False
    _app_module.app.config["TESTING"] = True
    _app_module.init_db()

    try:
        yield _app_module
    finally:
        os.remove(db_path)


@pytest.fixture
def conn(app_module):
    connection = app_module.get_db_connection()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def client(app_module):
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def admin_client(client):
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client
