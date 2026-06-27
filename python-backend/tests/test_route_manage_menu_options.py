def test_manage_menu_options_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin/menu-options")
    assert resp.status_code == 200
    assert "Opciones del Menú".encode("utf-8") in resp.data


def test_manage_menu_options_blocks_non_admin(client):
    client.post("/login", data={"username": "user", "password": "user123"})
    resp = client.get("/admin/menu-options")
    assert resp.status_code == 302


def test_add_menu_option_redirects_to_manage_menu_options(admin_client):
    resp = admin_client.post(
        "/admin/menu-options/add",
        data={"category": "beverage", "name": "Limonada", "icon": "🍋", "price": "20"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/menu-options"


def test_manage_menu_options_shows_added_option(admin_client):
    admin_client.post(
        "/admin/menu-options/add",
        data={"category": "beverage", "name": "Limonada Especial", "icon": "🍋", "price": "20"},
    )
    resp = admin_client.get("/admin/menu-options")
    assert "Limonada Especial".encode("utf-8") in resp.data


def test_delete_menu_option_redirects_to_manage_menu_options(admin_client, app_module):
    admin_client.post(
        "/admin/menu-options/add",
        data={"category": "beverage", "name": "Temp Drink", "icon": "🥤", "price": "10"},
    )
    conn = app_module.get_db_connection()
    option_id = conn.execute("SELECT id FROM menu_options WHERE name='Temp Drink'").fetchone()["id"]

    resp = admin_client.post(f"/admin/menu-options/delete/{option_id}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/menu-options"


def test_toggle_menu_option_redirects_to_manage_menu_options(admin_client, app_module):
    admin_client.post(
        "/admin/menu-options/add",
        data={"category": "beverage", "name": "Temp Drink 2", "icon": "🥤", "price": "10"},
    )
    conn = app_module.get_db_connection()
    option_id = conn.execute("SELECT id FROM menu_options WHERE name='Temp Drink 2'").fetchone()["id"]

    resp = admin_client.post(f"/admin/menu-options/toggle/{option_id}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/menu-options"
