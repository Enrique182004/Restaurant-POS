"""Auditoría v2.1.1 — admin de opciones de menú (bug 6).

Cubre el 500 al renombrar una bebida a un nombre ya presente en menu_prices,
los huérfanos de menu_prices al borrar, y la reactivación que ignoraba el precio."""


def _add(client, name, price, category='beverage', icon='🥤'):
    return client.post('/admin/menu-options/add', data={
        'category': category, 'name': name, 'icon': icon, 'price': str(price),
    })


def _option_id(app_module, name, category='beverage'):
    conn = app_module.get_db_connection()
    try:
        row = conn.execute(
            'SELECT id FROM menu_options WHERE name=? AND category=?', (name, category)
        ).fetchone()
        return row['id'] if row else None
    finally:
        conn.close()


def _option_row(app_module, option_id):
    conn = app_module.get_db_connection()
    try:
        return conn.execute(
            'SELECT active, price, name FROM menu_options WHERE id=?', (option_id,)
        ).fetchone()
    finally:
        conn.close()


def _price_row(app_module, key):
    conn = app_module.get_db_connection()
    try:
        return conn.execute('SELECT * FROM menu_prices WHERE key=?', (key,)).fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Rename collision no longer 500s
# ---------------------------------------------------------------------------

def test_rename_beverage_to_existing_price_key_does_not_500(admin_client, app_module):
    _add(admin_client, 'Coca', 25)
    _add(admin_client, 'Pepsi', 25)
    pepsi_id = _option_id(app_module, 'Pepsi')

    resp = admin_client.post(f'/admin/menu-options/update/{pepsi_id}',
                             data={'name': 'Coca', 'icon': '🥤', 'price': '25'})
    # Redirige con error, NO revienta con 500
    assert resp.status_code == 302

    # Pepsi sigue existiendo sin cambios y ambos precios intactos
    assert _option_row(app_module, pepsi_id)['name'] == 'Pepsi'
    assert _price_row(app_module, 'Coca') is not None
    assert _price_row(app_module, 'Pepsi') is not None


def test_rename_beverage_to_new_name_syncs_menu_prices(admin_client, app_module):
    _add(admin_client, 'Jarrito', 22)
    jid = _option_id(app_module, 'Jarrito')

    resp = admin_client.post(f'/admin/menu-options/update/{jid}',
                             data={'name': 'Jarrito Mango', 'icon': '🥤', 'price': '30'})
    assert resp.status_code == 302
    assert _price_row(app_module, 'Jarrito') is None
    new_row = _price_row(app_module, 'Jarrito Mango')
    assert new_row is not None
    assert new_row['price'] == 30


# ---------------------------------------------------------------------------
# Delete removes the menu_prices row (no orphan)
# ---------------------------------------------------------------------------

def test_delete_beverage_removes_menu_prices_row(admin_client, app_module):
    _add(admin_client, 'Fanta', 18)
    assert _price_row(app_module, 'Fanta') is not None
    fid = _option_id(app_module, 'Fanta')

    admin_client.post(f'/admin/menu-options/delete/{fid}')
    assert _price_row(app_module, 'Fanta') is None


# ---------------------------------------------------------------------------
# Reactivating an inactive option applies the newly submitted price/icon
# ---------------------------------------------------------------------------

def test_readd_inactive_beverage_updates_price(admin_client, app_module):
    _add(admin_client, 'Sprite', 20)
    sid = _option_id(app_module, 'Sprite')
    admin_client.post(f'/admin/menu-options/toggle/{sid}')  # inactiva

    _add(admin_client, 'Sprite', 30)  # re-agrega con precio nuevo

    opt = _option_row(app_module, sid)
    assert opt['active'] == 1
    assert opt['price'] == 30
    assert _price_row(app_module, 'Sprite')['price'] == 30
