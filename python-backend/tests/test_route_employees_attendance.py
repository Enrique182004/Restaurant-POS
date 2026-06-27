def test_employees_attendance_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin/employees")
    assert resp.status_code == 200
    assert "Asistencia".encode("utf-8") in resp.data


def test_employees_attendance_page_blocks_non_admin(client):
    client.post("/login", data={"username": "user", "password": "user123"})
    resp = client.get("/admin/employees")
    assert resp.status_code == 302


def test_employees_attendance_shows_employee_total(admin_client, app_module):
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "pay_amount": "1000", "days": ["1", "2", "3"]},
    )
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]
    conn.execute(
        "INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)", (employee_id, "2026-06-23")
    )
    conn.commit()

    resp = admin_client.get("/admin/employees?week=2026-06-22")
    assert resp.status_code == 200
    assert "333.33".encode("utf-8") in resp.data
