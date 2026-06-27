def test_add_employee_requires_login(client):
    resp = client.post("/admin/employees/add", data={"name": "Ana"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_add_employee_creates_employee_and_schedule(admin_client, app_module):
    resp = admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "pay_amount": "1000", "days": ["1", "2", "3"]},
    )
    assert resp.status_code == 302

    conn = app_module.get_db_connection()
    employee = conn.execute("SELECT * FROM employees WHERE name = 'Ana'").fetchone()
    assert employee is not None

    schedule = conn.execute(
        "SELECT * FROM employee_schedules WHERE employee_id = ?", (employee["id"],)
    ).fetchone()
    assert schedule["scheduled_days"] == "1,2,3"
    assert schedule["pay_amount"] == 1000.0


def test_add_employee_rejects_no_days_selected(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Ana", "pay_amount": "1000"})
    conn = app_module.get_db_connection()
    assert conn.execute("SELECT * FROM employees WHERE name = 'Ana'").fetchone() is None


def test_add_employee_rejects_zero_pay(admin_client, app_module):
    admin_client.post(
        "/admin/employees/add", data={"name": "Ana", "pay_amount": "0", "days": ["1"]}
    )
    conn = app_module.get_db_connection()
    assert conn.execute("SELECT * FROM employees WHERE name = 'Ana'").fetchone() is None
