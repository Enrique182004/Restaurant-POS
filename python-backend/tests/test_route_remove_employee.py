def test_remove_employee_hard_deletes_when_no_attendance(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Ana", "pay_amount": "1000", "days": ["1"]})
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]

    admin_client.post(f"/admin/employees/remove/{employee_id}")

    conn = app_module.get_db_connection()
    assert conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone() is None
    assert conn.execute(
        "SELECT * FROM employee_schedules WHERE employee_id=?", (employee_id,)
    ).fetchone() is None


def test_remove_employee_deactivates_when_attendance_exists(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Ana", "pay_amount": "1000", "days": ["1"]})
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]
    conn.execute(
        "INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)", (employee_id, "2026-06-23")
    )
    conn.commit()

    admin_client.post(f"/admin/employees/remove/{employee_id}")

    conn = app_module.get_db_connection()
    employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    assert employee is not None
    assert employee["active"] == 0
