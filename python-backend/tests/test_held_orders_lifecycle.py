"""Órdenes retenidas: deben sobrevivir logout/login y borrarse solo al cobrar."""
import os
import sqlite3


CART_ITEM = {
    'type': 'Bebida',
    'name': 'Agua',
    'beverage_type': 'Agua',
    'price': 10.0,
    'unit_price': 10.0,
    'quantity': 1,
}


def _set_cart(client, items):
    with client.session_transaction() as sess:
        sess['cart'] = items


def _held_rows():
    conn = sqlite3.connect(os.environ['RESTAURANT_DB_PATH'])
    rows = conn.execute('SELECT id, order_ref FROM held_orders').fetchall()
    conn.close()
    return rows


def _hold(client):
    _set_cart(client, [dict(CART_ITEM)])
    client.post('/hold_order')
    return _held_rows()[-1][0]


def test_resume_does_not_delete_held_order(admin_client):
    held_id = _hold(admin_client)
    resp = admin_client.post(f'/resume_order/{held_id}')
    assert resp.status_code == 302
    assert any(r[0] == held_id for r in _held_rows())
    with admin_client.session_transaction() as sess:
        assert sess['held_id'] == held_id
        assert sess['cart']


def test_held_order_survives_logout_and_login(admin_client):
    held_id = _hold(admin_client)
    admin_client.post(f'/resume_order/{held_id}')
    admin_client.post('/logout')
    assert any(r[0] == held_id for r in _held_rows())
    admin_client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    resp = admin_client.get('/api/held_orders')
    refs = [o['id'] for o in resp.get_json()['held_orders']]
    assert held_id in refs


def test_paying_resumed_order_removes_it_from_queue(admin_client):
    held_id = _hold(admin_client)
    admin_client.post(f'/resume_order/{held_id}')
    resp = admin_client.post('/ticket', data={
        'payment_method': 'cash',
        'amount_paid': '50.00',
    })
    assert resp.status_code == 200
    assert not any(r[0] == held_id for r in _held_rows())
    with admin_client.session_transaction() as sess:
        assert 'held_id' not in sess


def test_reholding_resumed_order_does_not_duplicate(admin_client):
    held_id = _hold(admin_client)
    admin_client.post(f'/resume_order/{held_id}')
    admin_client.post('/hold_order')
    rows = _held_rows()
    assert len(rows) == 1
    assert rows[0][0] != held_id  # nueva fila, la anterior reemplazada


def test_cancel_and_start_over_keeps_order_in_queue(admin_client):
    held_id = _hold(admin_client)
    admin_client.post(f'/resume_order/{held_id}')
    admin_client.post('/new_order')
    assert any(r[0] == held_id for r in _held_rows())
    with admin_client.session_transaction() as sess:
        assert 'held_id' not in sess
        assert sess['cart'] == []


def test_normal_sale_without_resume_touches_no_held_orders(admin_client):
    held_id = _hold(admin_client)
    _set_cart(admin_client, [dict(CART_ITEM)])
    resp = admin_client.post('/ticket', data={
        'payment_method': 'cash',
        'amount_paid': '50.00',
    })
    assert resp.status_code == 200
    assert any(r[0] == held_id for r in _held_rows())
