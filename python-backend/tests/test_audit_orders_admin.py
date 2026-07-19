"""Audit v2.1.1 — routes_orders_admin fixes.

Covers:
  #1/#2  calendar-day windows so Historial/CSV agree with reports() for a day
          containing a noon (12:00) and an evening (18:00) order.
  #3      period totals computed over the FULL filtered range, not just the
          latest 500 rendered rows.
  #4      void_order flashes an error for a nonexistent id.
"""
import json
import uuid
from datetime import datetime, timedelta


def _insert_order(conn, total, date_str, status='completed'):
    oid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO orders (id, items, total, payment_method, amount_paid, "
        "change_amount, date, status, customer_name) "
        "VALUES (?, ?, ?, 'cash', ?, 0, ?, ?, 'Cliente')",
        (oid, json.dumps([{"name": "Test", "quantity": 1, "price": total}]),
         total, total, date_str, status),
    )
    conn.commit()
    return oid


# ---- #1 / #2: calendar-day window, noon + evening order both visible ----

def test_history_today_includes_noon_and_evening(admin_client, conn):
    today = datetime.now().strftime('%Y-%m-%d')
    _insert_order(conn, 12.0, f"{today} 12:00:00")
    _insert_order(conn, 18.0, f"{today} 18:00:00")

    r = admin_client.get('/admin/orders?period=today')
    assert r.status_code == 200
    # Both orders' day total ($30.00) must appear (day-header total).
    assert b'$30.00' in r.data


def test_csv_export_today_row_count_matches(admin_client, conn):
    today = datetime.now().strftime('%Y-%m-%d')
    _insert_order(conn, 12.0, f"{today} 12:00:00")
    _insert_order(conn, 18.0, f"{today} 18:00:00")

    r = admin_client.get('/admin/orders/export?period=today')
    assert r.status_code == 200
    body = r.data.decode('utf-8-sig')
    data_rows = [ln for ln in body.splitlines() if ln.strip()][1:]  # drop header
    assert len(data_rows) == 2


def test_history_and_csv_agree_for_day(admin_client, conn):
    """History summary total and CSV both count the noon + evening orders."""
    today = datetime.now().strftime('%Y-%m-%d')
    _insert_order(conn, 12.0, f"{today} 12:00:00")
    _insert_order(conn, 18.0, f"{today} 18:00:00")

    hist = admin_client.get('/admin/orders?period=today')
    assert b'$30.00' in hist.data  # summary-bar-rev

    csv_body = admin_client.get('/admin/orders/export?period=today').data.decode('utf-8-sig')
    data_rows = [ln for ln in csv_body.splitlines() if ln.strip()][1:]
    assert len(data_rows) == 2


def test_custom_day_full_calendar_day(admin_client, conn):
    """A 09:00 order (previously hidden by the 16:00 clamp) is now included."""
    day = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    _insert_order(conn, 42.0, f"{day} 09:00:00")

    r = admin_client.get(f'/admin/orders?period=custom&date={day}')
    assert r.status_code == 200
    assert b'$42.00' in r.data


# ---- #3: totals over the FULL range, not just latest 500 ----

def test_summary_total_exceeds_500_rows(admin_client, conn):
    today = datetime.now().strftime('%Y-%m-%d')
    n = 600
    for i in range(n):
        # spread times across the day, all within the calendar day
        hh = 8 + (i % 12)
        mm = i % 60
        ss = i % 60
        _insert_order(conn, 1.0, f"{today} {hh:02d}:{mm:02d}:{ss:02d}")

    r = admin_client.get('/admin/orders?period=today')
    assert r.status_code == 200
    # True revenue is 600 * $1.00 = $600.00; must not understate to $500.00.
    assert b'$600.00' in r.data
    assert b'$500.00' not in r.data


# ---- #4: void nonexistent id flashes error ----

def test_void_nonexistent_flashes_error(admin_client, conn):
    r = admin_client.post('/admin/void_order/does-not-exist', follow_redirects=True)
    assert r.status_code == 200
    assert 'Orden no encontrada.'.encode() in r.data


def test_void_existing_flashes_success(admin_client, conn, app_module):
    today = datetime.now().strftime('%Y-%m-%d')
    oid = _insert_order(conn, 50.0, f"{today} 12:00:00")

    r = admin_client.post(f'/admin/void_order/{oid}', follow_redirects=True)
    assert r.status_code == 200
    assert 'anulada'.encode() in r.data
    fresh = app_module.get_db_connection()
    row = fresh.execute("SELECT status FROM orders WHERE id = ?", (oid,)).fetchone()
    assert row['status'] == 'voided'
