def test_resolve_employee_schedule_picks_version_active_for_the_week(app_module, conn):
    conn.execute("INSERT INTO employees (name) VALUES ('Ana')")
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]
    conn.execute(
        "INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, "2026-06-01", "1,2,3", 1000.0),
    )
    conn.execute(
        "INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, "2026-06-29", "4,5,6", 1200.0),
    )
    conn.commit()

    current_week = app_module.resolve_employee_schedule(conn, employee_id, "2026-06-22")
    assert current_week["scheduled_days"] == "1,2,3"
    assert current_week["pay_amount"] == 1000.0

    future_week = app_module.resolve_employee_schedule(conn, employee_id, "2026-06-29")
    assert future_week["scheduled_days"] == "4,5,6"
    assert future_week["pay_amount"] == 1200.0


def test_resolve_employee_schedule_returns_none_before_any_version(app_module, conn):
    conn.execute("INSERT INTO employees (name) VALUES ('Ana')")
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]
    conn.execute(
        "INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, "2026-06-22", "1,2,3", 1000.0),
    )
    conn.commit()

    result = app_module.resolve_employee_schedule(conn, employee_id, "2026-06-15")
    assert result is None
