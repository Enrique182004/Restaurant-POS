def test_manage_promotions_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin/promotions")
    assert resp.status_code == 200
    assert "Promociones".encode("utf-8") in resp.data


def test_manage_promotions_blocks_non_admin(client):
    client.post("/login", data={"username": "user", "password": "user123"})
    resp = client.get("/admin/promotions")
    assert resp.status_code == 302


def test_add_promotion_redirects_to_manage_promotions(admin_client):
    resp = admin_client.post(
        "/admin/promotions/add",
        data={"name": "VERANO20", "type": "percentage", "value": "20"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/promotions"


def test_manage_promotions_shows_added_promotion(admin_client):
    admin_client.post(
        "/admin/promotions/add",
        data={"name": "INVIERNO15", "type": "percentage", "value": "15"},
    )
    resp = admin_client.get("/admin/promotions")
    assert "INVIERNO15".encode("utf-8") in resp.data


def test_delete_promotion_redirects_to_manage_promotions(admin_client, app_module):
    admin_client.post(
        "/admin/promotions/add",
        data={"name": "TEMP10", "type": "percentage", "value": "10"},
    )
    conn = app_module.get_db_connection()
    promo_id = conn.execute("SELECT id FROM promotions WHERE name='TEMP10'").fetchone()["id"]

    resp = admin_client.post(f"/admin/promotions/delete/{promo_id}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/promotions"


def test_toggle_promotion_redirects_to_manage_promotions(admin_client, app_module):
    admin_client.post(
        "/admin/promotions/add",
        data={"name": "TEMP5", "type": "percentage", "value": "5"},
    )
    conn = app_module.get_db_connection()
    promo_id = conn.execute("SELECT id FROM promotions WHERE name='TEMP5'").fetchone()["id"]

    resp = admin_client.post(f"/admin/promotions/toggle/{promo_id}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/promotions"
