def test_add_employee_requires_login(client):
    resp = client.post("/admin/employees/add", data={"name": "Ana"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_add_empleado_creates_employee_and_schedule(admin_client, app_module):
    # empleado: tarifa fija por día (200/300); no requiere pago semanal.
    resp = admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "role": "empleado", "days": ["1", "2", "3"]},
    )
    assert resp.status_code == 302

    conn = app_module.get_db_connection()
    employee = conn.execute("SELECT * FROM employees WHERE name = 'Ana'").fetchone()
    assert employee is not None
    assert employee["role"] == "empleado"

    schedule = conn.execute(
        "SELECT * FROM employee_schedules WHERE employee_id = ?", (employee["id"],)
    ).fetchone()
    assert schedule["scheduled_days"] == "1,2,3"
    assert schedule["pay_amount"] == 0.0


def test_add_gerente_stores_weekly_pay(admin_client, app_module):
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Gaby", "role": "gerente", "pay_amount": "2000",
              "days": ["1", "2", "3", "4", "5", "6"]},
    )
    conn = app_module.get_db_connection()
    employee = conn.execute("SELECT * FROM employees WHERE name = 'Gaby'").fetchone()
    assert employee["role"] == "gerente"
    schedule = conn.execute(
        "SELECT * FROM employee_schedules WHERE employee_id = ?", (employee["id"],)
    ).fetchone()
    assert schedule["pay_amount"] == 2000.0


def test_add_gerente_defaults_weekly_pay_when_blank(admin_client, app_module):
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Gaby", "role": "gerente", "days": ["1"]},
    )
    conn = app_module.get_db_connection()
    employee = conn.execute("SELECT * FROM employees WHERE name = 'Gaby'").fetchone()
    schedule = conn.execute(
        "SELECT * FROM employee_schedules WHERE employee_id = ?", (employee["id"],)
    ).fetchone()
    assert schedule["pay_amount"] == 2000.0


def test_add_employee_defaults_role_to_empleado(admin_client, app_module):
    admin_client.post(
        "/admin/employees/add", data={"name": "Ana", "days": ["1"]}
    )
    conn = app_module.get_db_connection()
    employee = conn.execute("SELECT * FROM employees WHERE name = 'Ana'").fetchone()
    assert employee["role"] == "empleado"


def test_add_employee_rejects_invalid_role(admin_client, app_module):
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "role": "jefe", "days": ["1"]},
    )
    conn = app_module.get_db_connection()
    assert conn.execute("SELECT * FROM employees WHERE name = 'Ana'").fetchone() is None


def test_add_employee_rejects_no_days_selected(admin_client, app_module):
    admin_client.post("/admin/employees/add", data={"name": "Ana", "role": "empleado"})
    conn = app_module.get_db_connection()
    assert conn.execute("SELECT * FROM employees WHERE name = 'Ana'").fetchone() is None


def test_add_gerente_rejects_zero_pay(admin_client, app_module):
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Gaby", "role": "gerente", "pay_amount": "0", "days": ["1"]},
    )
    conn = app_module.get_db_connection()
    assert conn.execute("SELECT * FROM employees WHERE name = 'Gaby'").fetchone() is None
