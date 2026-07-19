from datetime import datetime, timedelta

# audit v2.1.1: toggle_attendance now refuses to mark a day in a week where the
# employee has no effective schedule. add_employee sets the schedule effective
# from the CURRENT week's Monday, so tests must mark within the current week
# (a past/pre-hire week is now correctly rejected — see the dedicated test).

_TODAY = datetime.now()
_MONDAY = (_TODAY - timedelta(days=_TODAY.weekday())).strftime("%Y-%m-%d")
_WORK_DATE = (_TODAY - timedelta(days=_TODAY.weekday()) + timedelta(days=1)).strftime("%Y-%m-%d")


def test_toggle_attendance_marks_then_unmarks(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Ana", "pay_amount": "1000", "days": ["1"]})
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]

    admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": _WORK_DATE, "week": _MONDAY},
    )
    conn = app_module.get_db_connection()
    present = conn.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?", (employee_id, _WORK_DATE)
    ).fetchone()
    assert present is not None

    admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": _WORK_DATE, "week": _MONDAY},
    )
    conn = app_module.get_db_connection()
    gone = conn.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?", (employee_id, _WORK_DATE)
    ).fetchone()
    assert gone is None


def test_toggle_attendance_requires_login(client):
    resp = client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": "1", "work_date": _WORK_DATE},
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_toggle_attendance_double_submit_does_not_crash(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Beto", "pay_amount": "1000", "days": ["1"]})
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Beto'").fetchone()["id"]

    conn.execute(
        "INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)",
        (employee_id, _WORK_DATE),
    )
    conn.commit()

    resp = admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": _WORK_DATE, "week": _MONDAY},
    )
    assert resp.status_code == 302

    resp2 = admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": _WORK_DATE, "week": _MONDAY},
    )
    assert resp2.status_code == 302
