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
