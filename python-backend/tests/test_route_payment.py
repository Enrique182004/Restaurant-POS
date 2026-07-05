import pytest


BEBIDA_ITEM = {
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


# ---------------------------------------------------------------------------
# /payment — GET
# ---------------------------------------------------------------------------

def test_payment_empty_cart_redirects(admin_client):
    _set_cart(admin_client, [])
    resp = admin_client.get('/payment')
    assert resp.status_code == 302


def test_payment_with_items_loads(admin_client):
    _set_cart(admin_client, [BEBIDA_ITEM])
    resp = admin_client.get('/payment')
    assert resp.status_code == 200
    assert b'payment' in resp.data.lower() or b'pago' in resp.data.lower()


# ---------------------------------------------------------------------------
# /cash_payment — GET
# ---------------------------------------------------------------------------

def test_cash_payment_empty_cart_redirects(admin_client):
    _set_cart(admin_client, [])
    resp = admin_client.get('/cash_payment')
    assert resp.status_code == 302


def test_cash_payment_with_items_loads(admin_client):
    _set_cart(admin_client, [BEBIDA_ITEM])
    resp = admin_client.get('/cash_payment')
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /apply_coupon — POST
# ---------------------------------------------------------------------------

def test_apply_coupon_invalid_code_redirects(admin_client):
    _set_cart(admin_client, [BEBIDA_ITEM])
    resp = admin_client.post('/apply_coupon', data={'coupon_code': 'NOTREAL'})
    assert resp.status_code == 302


def test_apply_coupon_no_field_does_not_crash(admin_client):
    _set_cart(admin_client, [BEBIDA_ITEM])
    resp = admin_client.post('/apply_coupon', data={})
    assert resp.status_code == 302


def test_apply_coupon_valid_code_redirects(admin_client, app_module):
    conn = app_module.get_db_connection()
    conn.execute(
        'INSERT INTO promotions (name, type, value, min_purchase, applicable_items, active) VALUES (?, ?, ?, ?, ?, ?)',
        ('TESTDESC10', 'percentage', 10.0, 0, None, 1),
    )
    conn.commit()
    conn.close()

    _set_cart(admin_client, [BEBIDA_ITEM])
    resp = admin_client.post('/apply_coupon', data={'coupon_code': 'testdesc10'})
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# /ticket — GET and POST
# ---------------------------------------------------------------------------

def test_ticket_get_no_cart_does_not_crash(admin_client):
    _set_cart(admin_client, [])
    resp = admin_client.get('/ticket')
    assert resp.status_code in (200, 302)


def test_ticket_post_cash_with_valid_cart(admin_client):
    _set_cart(admin_client, [BEBIDA_ITEM])
    resp = admin_client.post('/ticket', data={
        'payment_method': 'cash',
        'amount_paid': '50.0',
    })
    assert resp.status_code == 200
    assert b'order' in resp.data.lower() or b'orden' in resp.data.lower() or b'gracias' in resp.data.lower()


def test_ticket_post_card_with_valid_cart(admin_client):
    _set_cart(admin_client, [BEBIDA_ITEM])
    resp = admin_client.post('/ticket', data={
        'payment_method': 'card',
        'amount_paid': '10.0',
    })
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /split_payment — GET
# ---------------------------------------------------------------------------

def test_split_payment_empty_cart_loads(admin_client):
    _set_cart(admin_client, [])
    resp = admin_client.get('/split_payment')
    assert resp.status_code == 200


def test_split_payment_with_items_loads(admin_client):
    _set_cart(admin_client, [BEBIDA_ITEM])
    resp = admin_client.get('/split_payment')
    assert resp.status_code == 200
