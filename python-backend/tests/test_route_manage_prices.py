def test_manage_prices_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin/prices")
    assert resp.status_code == 200
    assert "Gestión de Precios".encode("utf-8") in resp.data


def test_manage_prices_blocks_non_admin(client):
    client.post("/login", data={"username": "user", "password": "user123"})
    resp = client.get("/admin/prices")
    assert resp.status_code == 302


def test_update_prices_redirects_to_manage_prices(admin_client, app_module):
    conn = app_module.get_db_connection()
    a_key = conn.execute("SELECT key FROM menu_prices LIMIT 1").fetchone()["key"]
    resp = admin_client.post("/admin/prices/update", data={a_key: "99.50"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/prices"
