"""audit v2.1.1 — Fix 4: attendance can't be marked in a week with no schedule.

add_employee sets a schedule effective from the CURRENT week's Monday. Marking
attendance in an earlier (pre-hire) week left resolve_employee_schedule == None,
so compute_employee_pay paid $0 while the day was silently recorded as present.
The toggle now rejects that and records nothing.
"""
from datetime import datetime, timedelta


def _monday_of(dt):
    return (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")


def test_marking_pre_hire_week_is_rejected_and_records_nothing(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Cleo", "pay_amount": "700", "days": ["1"]})
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Cleo'").fetchone()["id"]

    # A week two weeks before hire — no schedule is effective there.
    now = datetime.now()
    pre_hire_day = now - timedelta(weeks=2)
    pre_hire_monday = _monday_of(pre_hire_day)
    work_date = pre_hire_day.strftime("%Y-%m-%d")

    resp = admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": work_date, "week": pre_hire_monday},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    conn = app_module.get_db_connection()
    recorded = conn.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?",
        (employee_id, work_date),
    ).fetchone()
    assert recorded is None


def test_marking_flashes_no_schedule_message(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Dario", "pay_amount": "700", "days": ["1"]})
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Dario'").fetchone()["id"]

    now = datetime.now()
    pre_hire_day = now - timedelta(weeks=2)
    work_date = pre_hire_day.strftime("%Y-%m-%d")

    resp = admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": work_date,
              "week": _monday_of(pre_hire_day)},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "no tiene horario vigente".encode("utf-8") in resp.data


def test_marking_current_week_still_works(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Elsa", "pay_amount": "700", "days": ["1"]})
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Elsa'").fetchone()["id"]

    now = datetime.now()
    monday = _monday_of(now)
    work_date = (now - timedelta(days=now.weekday()) + timedelta(days=1)).strftime("%Y-%m-%d")

    admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": work_date, "week": monday},
    )
    conn = app_module.get_db_connection()
    recorded = conn.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?",
        (employee_id, work_date),
    ).fetchone()
    assert recorded is not None
