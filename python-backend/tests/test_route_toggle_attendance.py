def test_toggle_attendance_marks_then_unmarks(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Ana", "pay_amount": "1000", "days": ["1"]})
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]

    admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": "2026-06-23", "week": "2026-06-22"},
    )
    conn = app_module.get_db_connection()
    present = conn.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?", (employee_id, "2026-06-23")
    ).fetchone()
    assert present is not None

    admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": "2026-06-23", "week": "2026-06-22"},
    )
    conn = app_module.get_db_connection()
    gone = conn.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?", (employee_id, "2026-06-23")
    ).fetchone()
    assert gone is None


def test_toggle_attendance_requires_login(client):
    resp = client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": "1", "work_date": "2026-06-23"},
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_toggle_attendance_double_submit_does_not_crash(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Beto", "pay_amount": "1000", "days": ["1"]})
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Beto'").fetchone()["id"]

    conn.execute(
        "INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)",
        (employee_id, "2026-06-23"),
    )
    conn.commit()

    resp = admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": "2026-06-23", "week": "2026-06-22"},
    )
    assert resp.status_code == 302

    resp2 = admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": "2026-06-23", "week": "2026-06-22"},
    )
    assert resp2.status_code == 302
