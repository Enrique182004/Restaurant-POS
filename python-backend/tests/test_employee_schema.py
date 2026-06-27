def test_employee_tables_exist(conn):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "employees" in tables
    assert "employee_schedules" in tables
    assert "attendance" in tables


def test_employee_schedules_unique_columns_present(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(employee_schedules)").fetchall()}
    assert cols == {"id", "employee_id", "effective_from", "scheduled_days", "pay_amount", "created_at"}


def test_attendance_enforces_one_row_per_employee_per_day(conn):
    conn.execute("INSERT INTO employees (name) VALUES ('Ana')")
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]
    conn.execute(
        "INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)",
        (employee_id, "2026-06-23"),
    )
    conn.commit()

    import sqlite3
    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)",
            (employee_id, "2026-06-23"),
        )
