def test_employees_attendance_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin/employees")
    assert resp.status_code == 200
    assert "Asistencia".encode("utf-8") in resp.data


def test_employees_attendance_page_blocks_non_admin(client):
    client.post("/login", data={"username": "user", "password": "user123"})
    resp = client.get("/admin/employees")
    assert resp.status_code == 302


def test_employees_attendance_shows_employee_total(admin_client, app_module):
    conn = app_module.get_db_connection()
    cur = conn.execute("INSERT INTO employees (name) VALUES (?)", ("Ana",))
    employee_id = cur.lastrowid
    # Schedule effective_from must be <= the queried week start
    conn.execute(
        "INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, "2026-06-22", "1,2,3", 1000),
    )
    conn.execute(
        "INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)", (employee_id, "2026-06-23")
    )
    conn.commit()

    resp = admin_client.get("/admin/employees?week=2026-06-22")
    assert resp.status_code == 200
    assert "333.33".encode("utf-8") in resp.data


def test_admin_dashboard_links_to_employees(admin_client):
    resp = admin_client.get("/admin")
    assert b"/admin/employees" in resp.data
