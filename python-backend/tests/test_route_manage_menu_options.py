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


# ---------------------------------------------------------------------------
# /admin/menu-options/update/<id> — editar nombre, icono y precio
# ---------------------------------------------------------------------------

def _add_and_get_id(admin_client, app_module, name, category='beverage', price='25'):
    admin_client.post('/admin/menu-options/add',
                      data={'category': category, 'name': name, 'icon': '🥤', 'price': price})
    conn = app_module.get_db_connection()
    row = conn.execute('SELECT id FROM menu_options WHERE name=?', (name,)).fetchone()
    conn.close()
    return row['id']


def test_update_menu_option_renames_and_reprices(admin_client, app_module):
    option_id = _add_and_get_id(admin_client, app_module, 'Limonada')
    resp = admin_client.post(f'/admin/menu-options/update/{option_id}',
                             data={'name': 'Limonada Grande', 'icon': '🍋', 'price': '30'})
    assert resp.status_code == 302
    conn = app_module.get_db_connection()
    row = conn.execute('SELECT name, icon, price FROM menu_options WHERE id=?', (option_id,)).fetchone()
    assert (row['name'], row['icon'], row['price']) == ('Limonada Grande', '🍋', 30.0)
    # bebidas: menu_prices debe seguir el rename para que el cobro use el precio nuevo
    price_row = conn.execute("SELECT price FROM menu_prices WHERE key='Limonada Grande'").fetchone()
    conn.close()
    assert price_row is not None and price_row['price'] == 30.0


def test_update_menu_option_rejects_duplicate_name(admin_client, app_module):
    _add_and_get_id(admin_client, app_module, 'Jamaica')
    option_id = _add_and_get_id(admin_client, app_module, 'Horchata')
    resp = admin_client.post(f'/admin/menu-options/update/{option_id}',
                             data={'name': 'Jamaica', 'price': '25'}, follow_redirects=True)
    assert 'Ya existe'.encode() in resp.data
    conn = app_module.get_db_connection()
    row = conn.execute('SELECT name FROM menu_options WHERE id=?', (option_id,)).fetchone()
    conn.close()
    assert row['name'] == 'Horchata'


def test_update_menu_option_rejects_empty_name(admin_client, app_module):
    option_id = _add_and_get_id(admin_client, app_module, 'Naranjada')
    resp = admin_client.post(f'/admin/menu-options/update/{option_id}',
                             data={'name': '  ', 'price': '25'}, follow_redirects=True)
    assert 'no puede quedar'.encode() in resp.data


# ---------------------------------------------------------------------------
# /admin/menu-options/reorder — drag & drop persiste sort_order
# ---------------------------------------------------------------------------

def test_reorder_menu_options_persists_new_order(admin_client, app_module):
    ids = [
        _add_and_get_id(admin_client, app_module, 'Ordenada A'),
        _add_and_get_id(admin_client, app_module, 'Ordenada B'),
        _add_and_get_id(admin_client, app_module, 'Ordenada C'),
    ]
    reordered = [ids[2], ids[0], ids[1]]
    resp = admin_client.post('/admin/menu-options/reorder', json={'ids': reordered})
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True
    conn = app_module.get_db_connection()
    rows = conn.execute(
        'SELECT id FROM menu_options WHERE id IN (?, ?, ?) ORDER BY sort_order',
        ids,
    ).fetchall()
    conn.close()
    assert [r['id'] for r in rows] == reordered
    # el orden nuevo llega al lado del cliente (get_menu_options usa sort_order)
    names = [o['name'] for o in app_module.get_menu_options('beverage')
             if o['name'].startswith('Ordenada')]
    assert names == ['Ordenada C', 'Ordenada A', 'Ordenada B']


def test_reorder_menu_options_rejects_bad_payload(admin_client):
    resp = admin_client.post('/admin/menu-options/reorder', json={'ids': ['x', 'y']})
    assert resp.status_code == 400
    resp = admin_client.post('/admin/menu-options/reorder', json={})
    assert resp.status_code == 400
