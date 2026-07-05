import pytest


# ---------------------------------------------------------------------------
# customize_rice_ball — GET
# ---------------------------------------------------------------------------

def test_rice_ball_get_loads_for_logged_in_user(admin_client):
    resp = admin_client.get("/customize/rice_ball")
    assert resp.status_code == 200
    assert b"arroz" in resp.data.lower() or "Bola de Arroz".encode("utf-8") in resp.data


def test_rice_ball_get_redirects_unauthenticated(client):
    resp = client.get("/customize/rice_ball")
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# customize_rice_ball — POST
# ---------------------------------------------------------------------------

def test_rice_ball_post_valid_adds_to_cart(admin_client):
    resp = admin_client.post(
        "/customize/rice_ball",
        data={"ingredients": ["Atún"], "style": "Fría", "sauce": "Spicy"},
    )
    assert resp.status_code == 302


def test_rice_ball_post_too_many_ingredients_returns_error(admin_client):
    resp = admin_client.post(
        "/customize/rice_ball",
        data={
            "ingredients": ["Atún", "Salmón", "Camarón", "Cangrejo", "Pulpo", "Pepino", "Aguacate"],
            "style": "Fría",
            "sauce": "Spicy",
        },
    )
    assert resp.status_code == 200
    assert "ingredientes" in resp.data.decode("utf-8").lower()


def test_rice_ball_post_no_ingredients_returns_error(admin_client):
    resp = admin_client.post(
        "/customize/rice_ball",
        data={"ingredients": [], "style": "Fría", "sauce": "Spicy"},
    )
    assert resp.status_code == 200
    assert "ingrediente" in resp.data.decode("utf-8").lower()


def test_rice_ball_post_ostion_with_5_regular_succeeds(admin_client):
    resp = admin_client.post(
        "/customize/rice_ball",
        data={
            "ingredients": ["Ostión", "Atún", "Salmón", "Camarón", "Cangrejo", "Pulpo"],
            "style": "Fría",
            "sauce": "Spicy",
        },
    )
    assert resp.status_code == 302


def test_rice_ball_post_ostion_with_1_regular_succeeds(admin_client):
    resp = admin_client.post(
        "/customize/rice_ball",
        data={"ingredients": ["Ostión", "Atún"], "style": "Fría", "sauce": "Spicy"},
    )
    assert resp.status_code == 302


def test_rice_ball_post_two_ostion_returns_error(admin_client):
    resp = admin_client.post(
        "/customize/rice_ball",
        data={"ingredients": ["Ostión", "Ostión", "Atún"], "style": "Fría", "sauce": "Spicy"},
    )
    assert resp.status_code == 200
    assert "Osti" in resp.data.decode("utf-8")


def test_rice_ball_post_missing_style_does_not_crash(admin_client):
    resp = admin_client.post(
        "/customize/rice_ball",
        data={"ingredients": ["Atún"], "sauce": "Spicy"},
    )
    assert resp.status_code in (200, 302)


# ---------------------------------------------------------------------------
# customize_sushi — GET
# ---------------------------------------------------------------------------

def test_sushi_get_loads_for_logged_in_user(admin_client):
    resp = admin_client.get("/customize/sushi")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# customize_sushi — POST
# ---------------------------------------------------------------------------

def test_sushi_post_valid_adds_to_cart(admin_client):
    resp = admin_client.post(
        "/customize/sushi",
        data={"ingredients": ["Salmón"], "style": "Frío", "prepared": "Sushi Preparado"},
    )
    assert resp.status_code == 302


def test_sushi_post_too_many_regular_returns_error(admin_client):
    resp = admin_client.post(
        "/customize/sushi",
        data={
            "ingredients": ["Salmón", "Atún", "Camarón", "Pulpo"],
            "style": "Frío",
            "prepared": "Sushi Preparado",
        },
    )
    assert resp.status_code == 200
    assert "ingredientes" in resp.data.decode("utf-8").lower()


def test_sushi_post_no_ingredients_returns_error(admin_client):
    resp = admin_client.post(
        "/customize/sushi",
        data={"ingredients": [], "style": "Frío", "prepared": "Sushi Preparado"},
    )
    assert resp.status_code == 200
    assert "ingrediente" in resp.data.decode("utf-8").lower()


def test_sushi_post_ostion_with_2_regular_succeeds(admin_client):
    resp = admin_client.post(
        "/customize/sushi",
        data={
            "ingredients": ["Ostión", "Salmón", "Atún"],
            "style": "Frío",
            "prepared": "Sushi Preparado",
        },
    )
    assert resp.status_code == 302


def test_sushi_post_two_ostion_returns_error(admin_client):
    resp = admin_client.post(
        "/customize/sushi",
        data={
            "ingredients": ["Ostión", "Ostión", "Salmón"],
            "style": "Frío",
            "prepared": "Sushi Preparado",
        },
    )
    assert resp.status_code == 200
    assert "Osti" in resp.data.decode("utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_cart(client, items):
    with client.session_transaction() as sess:
        sess["cart"] = items


def _rice_ball_item():
    return {
        "type": "Bola de Arroz",
        "name": "Bola de Arroz",
        "ingredients": ["Atún"],
        "style": "Fría",
        "sauce": "Spicy",
        "price": 115.0,
        "unit_price": 115.0,
        "quantity": 1,
    }


def _sushi_item():
    return {
        "type": "Sushi",
        "name": "Sushi",
        "ingredients": ["Salmón"],
        "style": "Frío",
        "prepared": "Sushi Preparado",
        "sauce": "Sushi Preparado",
        "price": 130.0,
        "unit_price": 130.0,
        "quantity": 1,
    }


# ---------------------------------------------------------------------------
# update_item
# ---------------------------------------------------------------------------

def test_update_item_rice_ball_valid_edit(admin_client):
    _set_cart(admin_client, [_rice_ball_item()])
    resp = admin_client.post(
        "/update_item/0",
        data={"ingredients": ["Salmón"], "style": "Empanizada", "sauce": "Spicy"},
    )
    assert resp.status_code == 302


def test_update_item_rice_ball_ostion_with_3_regular_succeeds(admin_client):
    _set_cart(admin_client, [_rice_ball_item()])
    resp = admin_client.post(
        "/update_item/0",
        data={
            "ingredients": ["Ostión", "Atún", "Salmón", "Camarón"],
            "style": "Fría",
            "sauce": "Spicy",
        },
    )
    assert resp.status_code == 302


def test_update_item_sushi_ostion_with_1_regular_succeeds(admin_client):
    _set_cart(admin_client, [_sushi_item()])
    resp = admin_client.post(
        "/update_item/0",
        data={
            "ingredients": ["Ostión", "Salmón"],
            "style": "Frío",
            "prepared": "Sushi Preparado",
        },
    )
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# view_cart
# ---------------------------------------------------------------------------

def test_view_cart_empty_loads(admin_client):
    _set_cart(admin_client, [])
    resp = admin_client.get("/cart")
    assert resp.status_code == 200


def test_view_cart_with_items_loads(admin_client):
    _set_cart(admin_client, [_rice_ball_item()])
    resp = admin_client.get("/cart")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# update_quantity
# ---------------------------------------------------------------------------

def test_update_quantity_increase_returns_success(admin_client):
    _set_cart(admin_client, [_rice_ball_item()])
    resp = admin_client.post("/update_quantity/0/3")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "new_item_price" in data
    assert "new_total" in data


def test_update_quantity_to_one_returns_success(admin_client):
    _set_cart(admin_client, [_rice_ball_item()])
    resp = admin_client.post("/update_quantity/0/1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


# ---------------------------------------------------------------------------
# remove_item
# ---------------------------------------------------------------------------

def test_remove_item_redirects(admin_client):
    _set_cart(admin_client, [_rice_ball_item()])
    resp = admin_client.post("/remove_item/0")
    assert resp.status_code == 302


def test_remove_item_decreases_cart_length(admin_client):
    _set_cart(admin_client, [_rice_ball_item(), _sushi_item()])
    admin_client.post("/remove_item/0")
    resp = admin_client.get("/cart")
    assert resp.status_code == 200
    with admin_client.session_transaction() as sess:
        assert len(sess.get("cart", [])) == 1
