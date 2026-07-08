import io
import os
import sqlite3


# ---------------------------------------------------------------------------
# Helpers
#
# NOTE: these tests open direct sqlite3 connections instead of using the
# `conn` fixture — request teardown closes the g-cached connection, so a
# fixture connection is not safe to reuse across HTTP requests here.
# ---------------------------------------------------------------------------

def _direct_conn():
    return sqlite3.connect(os.environ["RESTAURANT_DB_PATH"])


def _menu_price(key):
    c = _direct_conn()
    try:
        return c.execute("SELECT price FROM menu_prices WHERE key = ?", (key,)).fetchone()[0]
    finally:
        c.close()


def _set_menu_price(key, price):
    c = _direct_conn()
    try:
        c.execute("UPDATE menu_prices SET price = ? WHERE key = ?", (price, key))
        c.commit()
    finally:
        c.close()


def _export(admin_client):
    resp = admin_client.get("/admin/respaldo/exportar")
    assert resp.status_code == 200
    return resp.data


def _import(admin_client, data, filename="respaldo.db", follow_redirects=False):
    return admin_client.post(
        "/admin/respaldo/importar",
        data={"respaldo": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
        follow_redirects=follow_redirects,
    )


# ---------------------------------------------------------------------------
# GET /admin/respaldo
# ---------------------------------------------------------------------------

def test_respaldo_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin/respaldo")
    assert resp.status_code == 200


def test_respaldo_page_redirects_unauthenticated(client):
    resp = client.get("/admin/respaldo")
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# GET /admin/respaldo/exportar
# ---------------------------------------------------------------------------

def test_export_returns_sqlite_attachment(admin_client):
    resp = admin_client.get("/admin/respaldo/exportar")
    assert resp.status_code == 200
    assert resp.data.startswith(b"SQLite format 3\x00")
    assert "attachment" in resp.headers["Content-Disposition"]


# ---------------------------------------------------------------------------
# POST /admin/respaldo/importar
# ---------------------------------------------------------------------------

def test_import_round_trip_restores_data(admin_client):
    original_price = _menu_price("Bola de Arroz")
    exported = _export(admin_client)

    _set_menu_price("Bola de Arroz", original_price + 50)
    assert _menu_price("Bola de Arroz") == original_price + 50

    resp = _import(admin_client, exported)
    assert resp.status_code == 302
    assert _menu_price("Bola de Arroz") == original_price


def test_import_clears_session(admin_client):
    exported = _export(admin_client)
    resp = _import(admin_client, exported)
    assert resp.status_code == 302

    resp = admin_client.get("/admin/respaldo")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_import_rejects_garbage_file(admin_client):
    original_price = _menu_price("Bola de Arroz")
    resp = _import(admin_client, b"this is definitely not a sqlite database",
                   filename="basura.db", follow_redirects=True)
    assert resp.status_code == 200
    assert "no es un respaldo válido".encode("utf-8") in resp.data
    assert _menu_price("Bola de Arroz") == original_price


def test_import_rejects_foreign_sqlite_file(admin_client, tmp_path):
    foreign_path = str(tmp_path / "foreign.db")
    foreign = sqlite3.connect(foreign_path)
    foreign.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY, note TEXT)")
    foreign.commit()
    foreign.close()
    with open(foreign_path, "rb") as f:
        foreign_bytes = f.read()

    original_price = _menu_price("Bola de Arroz")
    resp = _import(admin_client, foreign_bytes, filename="foreign.db",
                   follow_redirects=True)
    assert resp.status_code == 200
    assert "no es un respaldo válido".encode("utf-8") in resp.data
    assert _menu_price("Bola de Arroz") == original_price


def test_import_without_file_shows_error(admin_client):
    resp = admin_client.post(
        "/admin/respaldo/importar",
        data={},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Selecciona un archivo".encode("utf-8") in resp.data
