"""v2.1 hardening: POST-only ticket, NULL min_purchase, money() rounding, orders.date index."""
import os
import sqlite3

from business import money


CART_ITEM = {
    'type': 'Bebida',
    'name': 'Agua',
    'beverage_type': 'Agua',
    'price': 115.0,
    'unit_price': 115.0,
    'quantity': 1,
}


def _set_cart(client, items):
    with client.session_transaction() as sess:
        sess['cart'] = items


def _db():
    # Conexión directa: el fixture conn se cierra en el teardown de cada
    # request HTTP, así que no sirve para asserts posteriores a un request.
    conn = sqlite3.connect(os.environ['RESTAURANT_DB_PATH'])
    conn.row_factory = sqlite3.Row
    return conn


def _insert_promo(name, promo_type, value, min_purchase=0):
    conn = _db()
    conn.execute(
        "INSERT INTO promotions (name, type, value, min_purchase, applicable_items, active, description) "
        "VALUES (?, ?, ?, ?, NULL, 1, '')",
        (name, promo_type, value, min_purchase),
    )
    conn.commit()
    conn.close()


def _order_count():
    conn = _db()
    n = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    conn.close()
    return n


# ---------------------------------------------------------------------------
# money()
# ---------------------------------------------------------------------------

def test_money_rounds_float_noise_to_cents():
    assert money(103.50000000000001) == 103.5
    assert money(115 * 0.9) == 103.5


def test_money_half_up_not_bankers():
    # round() de Python usa banker's (2.675 -> 2.67); money() debe dar 2.68
    assert money(2.675) == 2.68
    assert money(0.005) == 0.01


def test_money_identity_on_clean_values():
    assert money(115.0) == 115.0
    assert money(0) == 0.0


# ---------------------------------------------------------------------------
# /ticket POST-only
# ---------------------------------------------------------------------------

def test_ticket_post_creates_exactly_one_order(admin_client):
    _set_cart(admin_client, [dict(CART_ITEM)])
    before = _order_count()
    resp = admin_client.post('/ticket', data={
        'payment_method': 'cash',
        'amount_paid': '200.00',
    })
    assert resp.status_code == 200
    assert _order_count() == before + 1


def test_ticket_get_returns_405(admin_client):
    _set_cart(admin_client, [dict(CART_ITEM)])
    before = _order_count()
    resp = admin_client.get('/ticket?payment_method=cash&amount_paid=200')
    assert resp.status_code == 405
    assert _order_count() == before


# ---------------------------------------------------------------------------
# Coupon: NULL min_purchase must not 500; exact split after % promo must pass
# ---------------------------------------------------------------------------

def test_apply_coupon_with_null_min_purchase_does_not_crash(admin_client):
    _insert_promo('NULLMIN', 'percentage', 10.0, min_purchase=None)
    _set_cart(admin_client, [dict(CART_ITEM)])
    resp = admin_client.post('/apply_coupon', data={'coupon_code': 'NULLMIN'},
                             follow_redirects=True)
    assert resp.status_code == 200
    with admin_client.session_transaction() as sess:
        assert sess['cart'][0]['price'] == 103.5


def test_exact_split_payment_after_percentage_promo(admin_client):
    _insert_promo('SPLIT10', 'percentage', 10.0)
    _set_cart(admin_client, [dict(CART_ITEM)])
    admin_client.post('/apply_coupon', data={'coupon_code': 'SPLIT10'})
    with admin_client.session_transaction() as sess:
        # Sin money() esto era 103.50000000000001 y el pago exacto fallaba
        assert sess['cart'][0]['price'] == 103.5
    resp = admin_client.post('/ticket', data={
        'payment_method': 'split',
        'cash_portion': '100.00',
        'card_portion': '3.50',
    })
    assert resp.status_code == 200
    conn = _db()
    row = conn.execute(
        'SELECT total, amount_paid FROM orders ORDER BY date DESC LIMIT 1'
    ).fetchone()
    conn.close()
    assert row['total'] == 103.5
    assert row['amount_paid'] == 103.5


# ---------------------------------------------------------------------------
# Schema: orders.date index
# ---------------------------------------------------------------------------

def test_orders_date_index_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_orders_date'"
    ).fetchone()
    assert row is not None
