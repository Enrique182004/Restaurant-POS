"""audit v2.1.1 — Fix 3: Kuike periods now have an upper bound.

Every query was `date >= start`, so 'ayer' (yesterday) leaked today's rows.
With $40 yesterday and $60 today, the 'ayer' sales summary must report $40.
"""
import os
import sqlite3
from datetime import datetime, timedelta


def _direct_conn():
    return sqlite3.connect(os.environ["RESTAURANT_DB_PATH"])


def _insert_order(oid, total, when):
    c = _direct_conn()
    try:
        c.execute(
            "INSERT INTO orders (id, items, total, payment_method, amount_paid, "
            "change_amount, date, status, customer_name) "
            "VALUES (?, '[]', ?, 'cash', ?, 0, ?, 'completed', 'Cliente')",
            (oid, total, total, when.strftime("%Y-%m-%d %H:%M:%S")),
        )
        c.commit()
    finally:
        c.close()


def _ask(admin_client, message):
    resp = admin_client.post(
        "/admin/kuike/chat",
        json={"messages": [{"role": "user", "content": message}]},
    )
    assert resp.status_code == 200
    return resp.get_json()["reply"]


def _seed_yesterday_and_today():
    now = datetime.now()
    # Yesterday at noon is safely inside yesterday's [00:00, 23:59:59] window.
    yesterday = (now - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    # "Today" uses the current instant so it is never in the future relative to
    # the period's upper bound (now), regardless of the wall-clock time of the run.
    _insert_order("ord-yest", 40.0, yesterday)
    _insert_order("ord-today", 60.0, now)


def test_yesterday_excludes_today(admin_client):
    _seed_yesterday_and_today()
    reply = _ask(admin_client, "ventas de ayer")
    assert "40.00" in reply
    assert "100" not in reply
    assert "60.00" not in reply


def test_today_excludes_yesterday(admin_client):
    _seed_yesterday_and_today()
    reply = _ask(admin_client, "ventas de hoy")
    assert "60.00" in reply
    assert "100" not in reply
    assert "40.00" not in reply
