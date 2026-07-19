def _add_employee(conn, name, role, pay_amount, scheduled_days="1,2,3"):
    cur = conn.execute("INSERT INTO employees (name, role) VALUES (?, ?)", (name, role))
    employee_id = cur.lastrowid
    conn.execute(
        "INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, "2026-06-22", scheduled_days, pay_amount),
    )
    return employee_id


def _mark(conn, employee_id, *dates):
    for d in dates:
        conn.execute(
            "INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)", (employee_id, d)
        )


# ── empleado: $200 lun–jue, $300 vie–dom por día trabajado ──────────────────

def test_empleado_weekday_days_pay_200_each(app_module, conn):
    employee_id = _add_employee(conn, "Ana", "empleado", 0, "1,2,3")
    _mark(conn, employee_id, "2026-06-23", "2026-06-24")  # Tue, Wed
    conn.commit()

    total_pay, per_day_rate, days_worked, scheduled_days = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 2
    assert scheduled_days == [1, 2, 3]
    assert total_pay == 400.0
    assert per_day_rate == 0.0  # la tarifa varía por día, no hay tarifa única


def test_empleado_weekend_days_pay_300_each(app_module, conn):
    employee_id = _add_employee(conn, "Beto", "empleado", 0, "4,5,6")
    _mark(conn, employee_id, "2026-06-26", "2026-06-27", "2026-06-28")  # Fri, Sat, Sun
    conn.commit()

    total_pay, _, days_worked, _ = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 3
    assert total_pay == 900.0


def test_empleado_mixed_week_sums_per_day_rates(app_module, conn):
    employee_id = _add_employee(conn, "Caro", "empleado", 0, "1,2,3,4,5,6")
    # Mon(200) + Thu(200) + Fri(300) + Sun(300)
    _mark(conn, employee_id, "2026-06-22", "2026-06-25", "2026-06-26", "2026-06-28")
    conn.commit()

    total_pay, _, days_worked, _ = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 4
    assert total_pay == 1000.0


def test_empleado_day_rate_boundaries(app_module):
    from business import empleado_day_rate
    assert empleado_day_rate("2026-06-25") == 200.0  # jueves
    assert empleado_day_rate("2026-06-26") == 300.0  # viernes
    assert empleado_day_rate("2026-06-28") == 300.0  # domingo
    assert empleado_day_rate("2026-06-22") == 200.0  # lunes


# ── gerente: semanal fijo dividido entre 6 días ──────────────────────────────

def test_gerente_full_six_days_earns_full_weekly(app_module, conn):
    employee_id = _add_employee(conn, "Gaby", "gerente", 2000.0, "1,2,3,4,5,6")
    _mark(conn, employee_id, "2026-06-23", "2026-06-24", "2026-06-25",
          "2026-06-26", "2026-06-27", "2026-06-28")
    conn.commit()

    total_pay, per_day_rate, days_worked, _ = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 6
    assert round(per_day_rate, 2) == 333.33
    assert total_pay == 2000.0


def test_gerente_missing_day_subtracts_one_sixth(app_module, conn):
    employee_id = _add_employee(conn, "Hugo", "gerente", 2000.0, "1,2,3,4,5,6")
    _mark(conn, employee_id, "2026-06-23", "2026-06-24", "2026-06-25",
          "2026-06-26", "2026-06-27")  # 5 de 6 días
    conn.commit()

    total_pay, _, days_worked, _ = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 5
    assert total_pay == round(2000.0 / 6 * 5, 2)


def test_gerente_divisor_is_six_even_with_fewer_scheduled_days(app_module, conn):
    # Aunque solo estén programados 3 días, el divisor del gerente es fijo (6).
    employee_id = _add_employee(conn, "Iván", "gerente", 2000.0, "1,2,3")
    _mark(conn, employee_id, "2026-06-23")
    conn.commit()

    total_pay, per_day_rate, days_worked, _ = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 1
    assert round(per_day_rate, 2) == 333.33
    assert total_pay == round(2000.0 / 6, 2)


# ── casos comunes a ambos roles ───────────────────────────────────────────────

def test_compute_employee_pay_zero_when_no_schedule_yet(app_module, conn):
    conn.execute("INSERT INTO employees (name) VALUES ('Carla')")
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Carla'").fetchone()["id"]
    conn.commit()

    result = app_module.compute_employee_pay(conn, employee_id, "2026-06-22", "2026-06-28")
    assert result == (0.0, 0.0, 0, [])


def test_compute_employee_pay_zero_when_no_attendance_marked(app_module, conn):
    employee_id = _add_employee(conn, "Diego", "gerente", 2000.0, "1,2,3,4,5,6")
    conn.commit()

    total_pay, per_day_rate, days_worked, scheduled_days = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 0
    assert total_pay == 0.0
    assert round(per_day_rate, 2) == 333.33  # schedule exists, rate is nonzero
    assert scheduled_days == [1, 2, 3, 4, 5, 6]


def test_legacy_employee_without_role_defaults_to_empleado(app_module, conn):
    # Filas creadas antes de la migración: role llega como default 'empleado'.
    conn.execute("INSERT INTO employees (name) VALUES ('Legacy')")
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Legacy'").fetchone()["id"]
    conn.execute(
        "INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) "
        "VALUES (?, ?, ?, ?)",
        (employee_id, "2026-06-22", "1,2,3", 1000.0),
    )
    _mark(conn, employee_id, "2026-06-27")  # sábado
    conn.commit()

    total_pay, _, days_worked, _ = app_module.compute_employee_pay(
        conn, employee_id, "2026-06-22", "2026-06-28"
    )
    assert days_worked == 1
    assert total_pay == 300.0
