import importlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def app_module():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    os.environ["RESTAURANT_DB_PATH"] = db_path
    os.environ["SECRET_KEY"] = "test-secret-key-not-for-prod"

    import app as _app_module
    importlib.reload(_app_module)
    _app_module.app.config["WTF_CSRF_ENABLED"] = False
    _app_module.app.config["TESTING"] = True
    _app_module.init_db()

    yield _app_module

    os.remove(db_path)


@pytest.fixture
def conn(app_module):
    return app_module.get_db_connection()


@pytest.fixture
def client(app_module):
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def admin_client(client):
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client
