def test_compute_employee_pay_prorates_for_missed_days(app_module, conn):
    conn.execute("INSERT INTO employees (name) VALUES ('Ana')")
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]
    conn.execute(
        "INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, "2026-06-22", "1,2,3", 1000.0),  # Tue/Wed/Thu, $1000/week
    )
    conn.execute("INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)", (employee_id, "2026-06-23"))
    conn.execute("INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)", (employee_id, "2026-06-24"))
    conn.commit()

    total_pay, per_day_rate, days_worked, scheduled_days = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 2
    assert scheduled_days == [1, 2, 3]
    assert round(per_day_rate, 2) == 333.33
    assert total_pay == round(1000.0 / 3 * 2, 2)


def test_compute_employee_pay_counts_extra_unscheduled_day(app_module, conn):
    conn.execute("INSERT INTO employees (name) VALUES ('Beto')")
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Beto'").fetchone()["id"]
    conn.execute(
        "INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, "2026-06-22", "4,5,6", 1000.0),  # Fri/Sat/Sun
    )
    for d in ("2026-06-26", "2026-06-27", "2026-06-28", "2026-06-25"):  # 3 scheduled + 1 extra (Thu)
        conn.execute("INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)", (employee_id, d))
    conn.commit()

    total_pay, per_day_rate, days_worked, _ = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 4
    assert total_pay == round((1000.0 / 3) * 4, 2)


def test_compute_employee_pay_zero_when_no_schedule_yet(app_module, conn):
    conn.execute("INSERT INTO employees (name) VALUES ('Carla')")
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Carla'").fetchone()["id"]
    conn.commit()

    result = app_module.compute_employee_pay(conn, employee_id, "2026-06-22", "2026-06-28")
    assert result == (0.0, 0.0, 0, [])


def test_compute_employee_pay_zero_when_no_attendance_marked(app_module, conn):
    conn.execute("INSERT INTO employees (name) VALUES ('Diego')")
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Diego'").fetchone()["id"]
    conn.execute(
        "INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, "2026-06-22", "1,2,3", 1000.0),
    )
    conn.commit()

    total_pay, per_day_rate, days_worked, scheduled_days = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 0
    assert total_pay == 0.0
    assert round(per_day_rate, 2) == 333.33  # schedule exists, rate is nonzero, just no attendance yet
    assert scheduled_days == [1, 2, 3]
