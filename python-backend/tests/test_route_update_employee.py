def test_update_employee_versions_schedule_for_next_week_only(admin_client, app_module):
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "role": "gerente", "pay_amount": "1000", "days": ["1", "2", "3"]},
    )
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]

    admin_client.post(
        f"/admin/employees/update/{employee_id}",
        data={"name": "Ana", "role": "gerente", "pay_amount": "1500", "days": ["4", "5", "6"]},
    )

    conn = app_module.get_db_connection()
    today_week_start, _ = app_module.get_week_bounds(app_module.datetime.now().strftime("%Y-%m-%d"))
    current = app_module.resolve_employee_schedule(conn, employee_id, today_week_start)
    assert current["scheduled_days"] == "1,2,3"
    assert current["pay_amount"] == 1000.0

    next_week_start = (
        app_module.datetime.strptime(today_week_start, "%Y-%m-%d") + app_module.timedelta(days=7)
    ).strftime("%Y-%m-%d")
    future = app_module.resolve_employee_schedule(conn, employee_id, next_week_start)
    assert future["scheduled_days"] == "4,5,6"
    assert future["pay_amount"] == 1500.0


def test_update_employee_renames(admin_client, app_module):
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "role": "empleado", "days": ["1"]},
    )
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]

    admin_client.post(
        f"/admin/employees/update/{employee_id}",
        data={"name": "Ana Maria", "role": "empleado", "days": ["1"]},
    )

    conn = app_module.get_db_connection()
    employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    assert employee["name"] == "Ana Maria"


def test_update_employee_changes_role(admin_client, app_module):
    # El rol aplica de inmediato (vive en employees, no en el horario versionado).
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "role": "empleado", "days": ["1"]},
    )
    conn = app_module.get_db_connection()
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]

    admin_client.post(
        f"/admin/employees/update/{employee_id}",
        data={"name": "Ana", "role": "gerente", "pay_amount": "2000", "days": ["1"]},
    )

    conn = app_module.get_db_connection()
    employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    assert employee["role"] == "gerente"
