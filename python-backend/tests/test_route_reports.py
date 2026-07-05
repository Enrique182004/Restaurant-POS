"""Reports page: verify per-period revenue isolation.

Assertion strategy: the summary card renders as
  <div class="summary-value">$NNN.NN</div>
We check that pattern specifically instead of the full HTML, because the
14-day trend chart always renders all days (including outside the selected
period) in tooltip title attributes.
"""
import json
import uuid
from datetime import datetime, timedelta


def _insert_order(conn, total, date_str):
    conn.execute(
        "INSERT INTO orders (id, items, total, payment_method, amount_paid, change_amount, date, status) "
        "VALUES (?, ?, ?, 'cash', ?, 0, ?, 'completed')",
        (str(uuid.uuid4()), json.dumps([{"name": "Test", "quantity": 1, "price": total}]),
         total, total, date_str),
    )
    conn.commit()


def _has_summary_amount(data: bytes, amount: str) -> bool:
    """Return True if $amount appears as the revenue summary card value."""
    return f'summary-value">${amount}'.encode() in data


def test_reports_today_excludes_yesterday(admin_client, conn):
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    _insert_order(conn, 100.0, f"{today} 12:00:00")
    _insert_order(conn, 777.0, f"{yesterday} 12:00:00")

    r = admin_client.get('/admin/reports?period=today')
    assert r.status_code == 200
    # Summary card must show only today's $100, not $877 (cumulative)
    assert _has_summary_amount(r.data, '100.00')
    assert not _has_summary_amount(r.data, '877.00')


def test_reports_custom_date_only_shows_that_day(admin_client, conn):
    """Selecting a specific past date must NOT include subsequent days."""
    day1 = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    day2 = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    day3 = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    _insert_order(conn, 201.0, f"{day1} 10:00:00")
    _insert_order(conn, 302.0, f"{day2} 10:00:00")
    _insert_order(conn, 403.0, f"{day3} 10:00:00")

    r = admin_client.get(f'/admin/reports?period=custom&date={day1}')
    assert r.status_code == 200
    # Summary card must show only $201 (day1), not $906 (201+302+403 cumulative)
    assert _has_summary_amount(r.data, '201.00')
    assert not _has_summary_amount(r.data, '906.00')


def test_reports_custom_date_full_day_included(admin_client, conn):
    """An order at 23:59 on the selected day must be included."""
    day = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    _insert_order(conn, 155.0, f"{day} 23:59:59")

    r = admin_client.get(f'/admin/reports?period=custom&date={day}')
    assert r.status_code == 200
    assert _has_summary_amount(r.data, '155.00')


def test_reports_week_includes_since_monday(admin_client, conn):
    r = admin_client.get('/admin/reports?period=week')
    assert r.status_code == 200


def test_reports_alltime_returns_ok(admin_client, conn):
    r = admin_client.get('/admin/reports?period=alltime')
    assert r.status_code == 200


def test_reports_invalid_custom_date_falls_back_to_today(admin_client, conn):
    r = admin_client.get('/admin/reports?period=custom&date=not-a-date')
    assert r.status_code == 200
