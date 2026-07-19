"""Auditoría v2.1.1 — /ticket: idempotencia, carrito vacío y montos inválidos.

Cubre bug 3 (doble-submit registra la venta dos veces), bug 4 (carrito vacío
crea orden de $0) y bug 5 (efectivo insuficiente / porciones negativas)."""
import os
import sqlite3


BEBIDA = {
    'type': 'Bebida', 'name': 'Agua', 'beverage_type': 'Agua',
    'price': 115.0, 'unit_price': 115.0, 'quantity': 1,
}


def _set_cart(client, items):
    with client.session_transaction() as sess:
        sess['cart'] = items


def _set_token(client, token):
    with client.session_transaction() as sess:
        sess['ticket_token'] = token


def _order_count():
    c = sqlite3.connect(os.environ['RESTAURANT_DB_PATH'])
    try:
        return c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Bug 3 — double-submit with the same token records exactly one order
# ---------------------------------------------------------------------------

def test_double_submit_same_token_creates_one_order(admin_client):
    _set_cart(admin_client, [dict(BEBIDA)])
    _set_token(admin_client, 'tok-123')
    before = _order_count()

    r1 = admin_client.post('/ticket', data={
        'payment_method': 'card', 'ticket_token': 'tok-123',
    })
    assert r1.status_code == 200

    # Reinyecta el mismo carrito (simula el 2º POST del navegador con el token viejo)
    _set_cart(admin_client, [dict(BEBIDA)])
    r2 = admin_client.post('/ticket', data={
        'payment_method': 'card', 'ticket_token': 'tok-123',
    })
    assert r2.status_code == 302  # rechazado, redirige a home
    assert _order_count() == before + 1


def test_stale_token_is_rejected(admin_client):
    _set_cart(admin_client, [dict(BEBIDA)])
    _set_token(admin_client, 'server-token')
    before = _order_count()

    resp = admin_client.post('/ticket', data={
        'payment_method': 'card', 'ticket_token': 'wrong-token',
    })
    assert resp.status_code == 302
    assert _order_count() == before


# ---------------------------------------------------------------------------
# Bug 4 — empty cart must not create a $0 completed order
# ---------------------------------------------------------------------------

def test_empty_cart_creates_no_order(admin_client):
    _set_cart(admin_client, [])
    before = _order_count()
    resp = admin_client.post('/ticket', data={'payment_method': 'card'})
    assert resp.status_code == 302
    assert _order_count() == before


# ---------------------------------------------------------------------------
# Bug 5 — cash underpay and negative split portions are rejected
# ---------------------------------------------------------------------------

def test_cash_underpay_rejected(admin_client):
    _set_cart(admin_client, [dict(BEBIDA)])  # total 115
    before = _order_count()
    resp = admin_client.post('/ticket', data={
        'payment_method': 'cash', 'amount_paid': '10.0',
    })
    assert resp.status_code == 302
    assert _order_count() == before


def test_split_negative_portion_rejected(admin_client):
    _set_cart(admin_client, [dict(BEBIDA)])
    before = _order_count()
    resp = admin_client.post('/ticket', data={
        'payment_method': 'split', 'cash_portion': '-5', 'card_portion': '120',
    })
    assert resp.status_code == 302
    assert _order_count() == before


def test_cash_exact_payment_still_succeeds(admin_client):
    _set_cart(admin_client, [dict(BEBIDA)])
    before = _order_count()
    resp = admin_client.post('/ticket', data={
        'payment_method': 'cash', 'amount_paid': '115.0',
    })
    assert resp.status_code == 200
    assert _order_count() == before + 1
