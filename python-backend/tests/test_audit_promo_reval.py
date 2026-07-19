"""Auditoría v2.1.1 — revalidación de promociones tras mutar el carrito.

Cubre los bugs 1 (promo no revalidada tras remove/update/qty) y 2 (cupón de
monto fijo aplicado por-línea en vez de por-orden)."""
import pytest


def _item(item_type, price, quantity=1, name=None):
    return {
        'type': item_type,
        'name': name or item_type,
        'price': float(price),
        'unit_price': float(price) / max(quantity, 1),
        'quantity': quantity,
    }


def _set_cart(client, items):
    with client.session_transaction() as sess:
        sess['cart'] = items


def _cart(client):
    with client.session_transaction() as sess:
        return sess.get('cart', [])


def _coupon_code(client):
    with client.session_transaction() as sess:
        return sess.get('coupon_code')


def _cart_total(client):
    return sum(i['price'] for i in _cart(client))


def _insert_promo(conn, name, promo_type, value, get_free=1, applicable=None,
                  min_purchase=0):
    conn.execute(
        'INSERT INTO promotions (name, type, value, min_purchase, applicable_items, '
        'active, description, get_free) VALUES (?, ?, ?, ?, ?, 1, ?, ?)',
        (name, promo_type, value, min_purchase, applicable, name, get_free),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Bug 1a — removing the PAID line of a 2x1 must not leave the free line at $0
# ---------------------------------------------------------------------------

def test_bxgy_remove_paid_line_drops_promo_no_free_zero(admin_client, conn):
    _insert_promo(conn, 'DOSXUNO', 'bxgy', 1, get_free=1)
    _set_cart(admin_client, [
        _item('Bola de Arroz', 115),
        _item('Bola de Arroz', 115),
    ])

    admin_client.post('/apply_coupon', data={'coupon_code': 'DOSXUNO'})
    cart = _cart(admin_client)
    # Exactamente una línea quedó gratis
    assert sum(1 for i in cart if i['price'] == 0) == 1
    paid_index = next(i for i, it in enumerate(cart) if it['price'] > 0)

    admin_client.post(f'/remove_item/{paid_index}')

    cart = _cart(admin_client)
    assert len(cart) == 1
    remaining = cart[0]
    assert remaining['price'] == 115  # precio completo, NO $0
    assert 'discount' not in remaining
    assert 'original_price' not in remaining
    assert _coupon_code(admin_client) is None  # cupón olvidado limpiamente


# ---------------------------------------------------------------------------
# Bug 1c — changing qty on one line reapplies a %-coupon across ALL lines
# ---------------------------------------------------------------------------

def test_percentage_qty_change_reapplies_consistently(admin_client, conn):
    _insert_promo(conn, 'DESC10', 'percentage', 10)
    _set_cart(admin_client, [
        _item('Bola de Arroz', 100),
        _item('Bola de Arroz', 100),
    ])
    admin_client.post('/apply_coupon', data={'coupon_code': 'DESC10'})

    # Sube la cantidad de la primera línea a 2 (base 200 -> 180 con 10%)
    admin_client.post('/update_quantity/0/2')

    cart = _cart(admin_client)
    # Ninguna línea con insignia de descuento sin original_price (sin huérfanos)
    for it in cart:
        assert ('discount' in it) == ('original_price' in it)
        assert 'discount' in it  # el 10% sigue aplicado a ambas líneas
    # Total = 10% de descuento sobre base (200 + 100)
    assert _cart_total(admin_client) == pytest.approx(270)
    assert _coupon_code(admin_client) == 'DESC10'


def test_bxgy_qty_change_drops_promo_when_no_longer_qualifies(admin_client, conn):
    _insert_promo(conn, 'DOSXUNO', 'bxgy', 1, get_free=1)
    _set_cart(admin_client, [
        _item('Bola de Arroz', 115),
        _item('Bola de Arroz', 115),
    ])
    admin_client.post('/apply_coupon', data={'coupon_code': 'DOSXUNO'})

    # Reducir todo a una sola unidad rompe el requisito de 2 -> promo cae limpio
    # (elimina una línea, deja una)
    cart = _cart(admin_client)
    free_index = next(i for i, it in enumerate(cart) if it['price'] == 0)
    admin_client.post(f'/remove_item/{free_index}')

    cart = _cart(admin_client)
    assert len(cart) == 1
    assert cart[0]['price'] == 115
    assert 'discount' not in cart[0]
    assert _coupon_code(admin_client) is None


# ---------------------------------------------------------------------------
# Bug 2 — fixed-amount coupon reduces the ORDER once, regardless of grouping
# ---------------------------------------------------------------------------

def test_fixed_coupon_reduces_order_once_single_line(admin_client, conn):
    _insert_promo(conn, 'MENOS20', 'fixed', 20)
    _set_cart(admin_client, [_item('Bola de Arroz', 345, quantity=3)])
    admin_client.post('/apply_coupon', data={'coupon_code': 'MENOS20'})
    assert _cart_total(admin_client) == pytest.approx(325)


def test_fixed_coupon_reduces_order_once_multiple_lines(admin_client, conn):
    _insert_promo(conn, 'MENOS20', 'fixed', 20)
    _set_cart(admin_client, [
        _item('Bola de Arroz', 115),
        _item('Bola de Arroz', 115),
        _item('Bola de Arroz', 115),
    ])
    admin_client.post('/apply_coupon', data={'coupon_code': 'MENOS20'})
    # $20 total, NO $20 por línea (que daría 345 - 60 = 285)
    assert _cart_total(admin_client) == pytest.approx(325)


def test_fixed_coupon_removal_restores_full_price(admin_client, conn):
    _insert_promo(conn, 'MENOS20', 'fixed', 20)
    _set_cart(admin_client, [
        _item('Bola de Arroz', 115),
        _item('Bola de Arroz', 115),
        _item('Bola de Arroz', 115),
    ])
    admin_client.post('/apply_coupon', data={'coupon_code': 'MENOS20'})
    admin_client.post('/remove_coupon')
    assert _cart_total(admin_client) == pytest.approx(345)
    for it in _cart(admin_client):
        assert 'discount' not in it
        assert 'original_price' not in it
    assert _coupon_code(admin_client) is None
