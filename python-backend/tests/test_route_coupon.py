import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_rice_ball(client):
    resp = client.post(
        "/customize/rice_ball",
        data={"ingredients": ["Atún"], "style": "Fría", "sauce": "Spicy"},
    )
    assert resp.status_code == 302


def _insert_promo(conn, name, promo_type, value):
    conn.execute(
        "INSERT INTO promotions (name, type, value, min_purchase, applicable_items, active, description) "
        "VALUES (?, ?, ?, 0, NULL, 1, '')",
        (name, promo_type, value),
    )
    conn.commit()


def _cart(client):
    with client.session_transaction() as sess:
        return sess.get("cart", [])


def _cart_total(client):
    return sum(item["price"] for item in _cart(client))


# ---------------------------------------------------------------------------
# apply_coupon
# ---------------------------------------------------------------------------

def test_percentage_coupon_reduces_total_10_percent(admin_client, conn):
    _insert_promo(conn, "DESC10", "percentage", 10)
    _add_rice_ball(admin_client)
    total_before = _cart_total(admin_client)
    assert total_before > 0

    resp = admin_client.post("/apply_coupon", data={"coupon_code": "DESC10"})
    assert resp.status_code == 302
    assert _cart_total(admin_client) == pytest.approx(total_before * 0.9)


def test_second_coupon_is_rejected_and_total_unchanged(admin_client, conn):
    _insert_promo(conn, "DESC10", "percentage", 10)
    _insert_promo(conn, "DESC20", "percentage", 20)
    _add_rice_ball(admin_client)
    admin_client.post("/apply_coupon", data={"coupon_code": "DESC10"})
    total_with_first = _cart_total(admin_client)

    resp = admin_client.post(
        "/apply_coupon", data={"coupon_code": "DESC20"}, follow_redirects=True
    )
    assert resp.status_code == 200
    assert "Ya hay una promoción aplicada".encode("utf-8") in resp.data
    assert _cart_total(admin_client) == pytest.approx(total_with_first)


# ---------------------------------------------------------------------------
# remove_coupon
# ---------------------------------------------------------------------------

def test_remove_coupon_restores_original_total(admin_client, conn):
    _insert_promo(conn, "DESC10", "percentage", 10)
    _add_rice_ball(admin_client)
    total_before = _cart_total(admin_client)
    admin_client.post("/apply_coupon", data={"coupon_code": "DESC10"})
    assert _cart_total(admin_client) == pytest.approx(total_before * 0.9)

    resp = admin_client.post("/remove_coupon")
    assert resp.status_code == 302
    assert _cart_total(admin_client) == pytest.approx(total_before)
    for item in _cart(admin_client):
        assert "discount" not in item
        assert "original_price" not in item


def test_reapply_coupon_after_removal_works(admin_client, conn):
    _insert_promo(conn, "DESC10", "percentage", 10)
    _insert_promo(conn, "DESC20", "percentage", 20)
    _add_rice_ball(admin_client)
    total_before = _cart_total(admin_client)

    admin_client.post("/apply_coupon", data={"coupon_code": "DESC10"})
    admin_client.post("/remove_coupon")

    resp = admin_client.post("/apply_coupon", data={"coupon_code": "DESC20"})
    assert resp.status_code == 302
    assert _cart_total(admin_client) == pytest.approx(total_before * 0.8)


def test_remove_coupon_without_promo_still_redirects(admin_client):
    _add_rice_ball(admin_client)
    total_before = _cart_total(admin_client)

    resp = admin_client.post("/remove_coupon")
    assert resp.status_code == 302
    assert _cart_total(admin_client) == pytest.approx(total_before)


def test_remove_coupon_unauthenticated_redirects_to_login(client):
    resp = client.post("/remove_coupon")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
