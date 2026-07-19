"""Pagos en dólares: conversión USD → MXN en /ticket, cambio siempre en MXN,
tipo de cambio configurable por el admin."""


def _seed_cart(client, app_module):
    client.post("/login", data={"username": "admin", "password": "admin123"})
    with client.session_transaction() as sess:
        sess["cart"] = [{"name": "Boneless", "type": "Boneless", "price": 105.0, "quantity": 1}]
        sess["order_id"] = "test1234"
        sess.pop("ticket_token", None)


def _set_rate(app_module, rate):
    conn = app_module.get_db_connection()
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES ('usd_rate', ?)", (str(rate),)
    )
    conn.commit()


def _last_order(app_module):
    conn = app_module.get_db_connection()
    return conn.execute("SELECT * FROM orders ORDER BY date DESC LIMIT 1").fetchone()


def test_usd_rate_seeded_by_default(app_module):
    conn = app_module.get_db_connection()
    row = conn.execute("SELECT value FROM config WHERE key = 'usd_rate'").fetchone()
    assert row is not None
    assert float(row["value"]) > 0


def test_cash_usd_payment_converts_and_gives_change_in_mxn(client, app_module):
    _seed_cart(client, app_module)
    _set_rate(app_module, 20.0)

    resp = client.post(
        "/ticket",
        data={"payment_method": "cash", "amount_paid": "10", "currency": "usd"},
    )
    assert resp.status_code == 200

    order = _last_order(app_module)
    assert order["paid_currency"] == "usd"
    assert order["paid_amount_usd"] == 10.0
    assert order["usd_rate"] == 20.0
    assert order["amount_paid"] == 200.0  # 10 USD × 20
    assert order["change_amount"] == 95.0  # 200 − 105, en MXN


def test_cash_usd_underpay_rejected_after_conversion(client, app_module):
    _seed_cart(client, app_module)
    _set_rate(app_module, 20.0)

    resp = client.post(
        "/ticket",
        data={"payment_method": "cash", "amount_paid": "5", "currency": "usd"},
    )
    # 5 USD × 20 = 100 < 105 → rechazado
    assert resp.status_code == 302
    assert _last_order(app_module) is None


def test_cash_mxn_payment_unaffected_by_currency_field(client, app_module):
    _seed_cart(client, app_module)
    _set_rate(app_module, 20.0)

    resp = client.post(
        "/ticket",
        data={"payment_method": "cash", "amount_paid": "200", "currency": "mxn"},
    )
    assert resp.status_code == 200
    order = _last_order(app_module)
    assert order["paid_currency"] == "mxn"
    assert order["paid_amount_usd"] == 0.0
    assert order["amount_paid"] == 200.0
    assert order["change_amount"] == 95.0


def test_card_payment_ignores_usd_currency(client, app_module):
    # La conversión aplica solo al efectivo; una tarjeta paga el total exacto en MXN.
    _seed_cart(client, app_module)
    _set_rate(app_module, 20.0)

    resp = client.post(
        "/ticket", data={"payment_method": "card", "currency": "usd"}
    )
    assert resp.status_code == 200
    order = _last_order(app_module)
    assert order["amount_paid"] == 105.0
    assert order["paid_amount_usd"] == 0.0


def test_split_with_usd_cash_portion_converts(client, app_module):
    _seed_cart(client, app_module)
    _set_rate(app_module, 20.0)

    resp = client.post(
        "/ticket",
        data={
            "payment_method": "split",
            "cash_portion": "5",       # 5 USD = 100 MXN
            "card_portion": "5",       # 5 MXN
            "cash_currency": "usd",
        },
    )
    assert resp.status_code == 200
    order = _last_order(app_module)
    assert order["paid_currency"] == "usd"
    assert order["paid_amount_usd"] == 5.0
    assert order["amount_paid"] == 105.0
    assert order["change_amount"] == 0.0


def test_split_usd_cash_overpay_gives_change_in_mxn(client, app_module):
    _seed_cart(client, app_module)
    _set_rate(app_module, 20.0)

    resp = client.post(
        "/ticket",
        data={
            "payment_method": "split",
            "cash_portion": "10",      # 10 USD = 200 MXN
            "card_portion": "5",
            "cash_currency": "usd",
        },
    )
    assert resp.status_code == 200
    order = _last_order(app_module)
    assert order["amount_paid"] == 205.0
    assert order["change_amount"] == 100.0


def test_split_rejects_card_over_total(client, app_module):
    _seed_cart(client, app_module)
    resp = client.post(
        "/ticket",
        data={"payment_method": "split", "cash_portion": "0", "card_portion": "500"},
    )
    assert resp.status_code == 302
    assert _last_order(app_module) is None


def test_split_usd_underpay_rejected(client, app_module):
    _seed_cart(client, app_module)
    _set_rate(app_module, 20.0)

    resp = client.post(
        "/ticket",
        data={
            "payment_method": "split",
            "cash_portion": "2",       # 2 USD = 40 MXN
            "card_portion": "50",
            "cash_currency": "usd",
        },
    )
    assert resp.status_code == 302
    assert _last_order(app_module) is None


def test_receipt_shows_usd_payment_and_mxn_change(client, app_module):
    _seed_cart(client, app_module)
    _set_rate(app_module, 20.0)

    client.post(
        "/ticket",
        data={"payment_method": "cash", "amount_paid": "10", "currency": "usd"},
    )
    conn = app_module.get_db_connection()
    job = conn.execute("SELECT receipt_content FROM print_jobs LIMIT 1").fetchone()
    assert job is not None
    assert "US$10.00" in job["receipt_content"]
    assert "TC $20.00" in job["receipt_content"]
    assert "CAMBIO (MXN): $95.00" in job["receipt_content"]


def test_split_receipt_itemizes_cash_and_card(client, app_module):
    _seed_cart(client, app_module)
    _set_rate(app_module, 20.0)

    client.post(
        "/ticket",
        data={
            "payment_method": "split",
            "cash_portion": "10",      # 10 USD = 200 MXN
            "card_portion": "5",
            "cash_currency": "usd",
        },
    )
    conn = app_module.get_db_connection()
    job = conn.execute("SELECT receipt_content FROM print_jobs LIMIT 1").fetchone()
    assert job is not None
    assert "EFECTIVO: US$10.00 (TC $20.00)" in job["receipt_content"]
    assert "= $200.00 MXN" in job["receipt_content"]
    assert "TARJETA:  $5.00" in job["receipt_content"]
    assert "CAMBIO (MXN): $100.00" in job["receipt_content"]


def test_invalid_currency_treated_as_mxn(client, app_module):
    _seed_cart(client, app_module)
    resp = client.post(
        "/ticket",
        data={"payment_method": "cash", "amount_paid": "150", "currency": "eur"},
    )
    assert resp.status_code == 200
    order = _last_order(app_module)
    assert order["paid_currency"] == "mxn"
    assert order["amount_paid"] == 150.0


# ── Configuración del tipo de cambio (admin) ─────────────────────────────────

def test_admin_updates_usd_rate(admin_client, app_module):
    resp = admin_client.post("/admin/config/update", data={"usd_rate": "19.50"})
    assert resp.status_code == 302
    conn = app_module.get_db_connection()
    row = conn.execute("SELECT value FROM config WHERE key = 'usd_rate'").fetchone()
    assert row["value"] == "19.50"


def test_admin_rejects_invalid_usd_rate(admin_client, app_module):
    _set_rate(app_module, 18.0)
    for bad in ("0", "-5", "abc"):
        admin_client.post("/admin/config/update", data={"usd_rate": bad})
    conn = app_module.get_db_connection()
    row = conn.execute("SELECT value FROM config WHERE key = 'usd_rate'").fetchone()
    assert row["value"] == "18.0"


def test_usd_rate_update_requires_admin(client, app_module):
    client.post("/login", data={"username": "user", "password": "user123"})
    _set_rate(app_module, 18.0)
    client.post("/admin/config/update", data={"usd_rate": "99"})
    conn = app_module.get_db_connection()
    row = conn.execute("SELECT value FROM config WHERE key = 'usd_rate'").fetchone()
    assert row["value"] == "18.0"


def test_printer_config_still_works(admin_client, app_module):
    admin_client.post("/admin/config/update", data={"printer_name": "MiImpresora"})
    conn = app_module.get_db_connection()
    row = conn.execute("SELECT value FROM config WHERE key = 'printer_name'").fetchone()
    assert row["value"] == "MiImpresora"
