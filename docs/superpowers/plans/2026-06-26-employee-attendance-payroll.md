# Employee Attendance & Payroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the admin manage a roster of employees, mark which days each one worked on a weekly Mon–Sun grid, and have weekly pay computed automatically (prorated per day), with schedule/pay edits only affecting future weeks.

**Architecture:** Three new SQLite tables (`employees`, `employee_schedules`, `attendance`) added to the existing `init_db()` in `app.py`. A handful of pure/DB helper functions compute week boundaries, resolve the schedule version active for a given week, and compute pay. Six new Flask routes (matching the existing `@login_required @admin_required` + CSRF + flash pattern) expose two pages: an "Asistencia" view (mark attendance, see totals, browse past weeks) and a "Gestionar empleados" view (add/edit/deactivate employees), linked by a shared tab control.

**Tech Stack:** Flask, raw `sqlite3` (no ORM, matching the rest of the codebase), Jinja2 templates, pytest (new — this codebase has no existing test suite).

**Spec:** `docs/superpowers/specs/2026-06-26-employee-attendance-payroll-design.md`

**Reference dates used in tests below:** 2026-06-22 is a Monday, 2026-06-28 is the following Sunday (same week), 2026-06-29 is the next Monday. These are real calendar dates — verified, not arbitrary.

---

## Task 1: Test infrastructure

This codebase has zero existing tests. We add a minimal pytest setup scoped to `python-backend/`, using a temp SQLite file per test so nothing touches the real `restaurant.db`.

**Files:**

- Modify: `python-backend/requirements.txt`
- Create: `python-backend/tests/conftest.py`
- Create: `python-backend/tests/test_smoke.py`

- [ ] **Step 1: Add pytest to requirements**

Append to `python-backend/requirements.txt`:

```
pytest==8.3.4
```

- [ ] **Step 2: Create the test fixtures**

Create `python-backend/tests/conftest.py`:

```python
import importlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def app_module():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    os.environ["RESTAURANT_DB_PATH"] = db_path
    os.environ["SECRET_KEY"] = "test-secret-key-not-for-prod"

    import app as _app_module
    importlib.reload(_app_module)
    _app_module.app.config["WTF_CSRF_ENABLED"] = False
    _app_module.app.config["TESTING"] = True
    _app_module.init_db()

    yield _app_module

    os.remove(db_path)


@pytest.fixture
def conn(app_module):
    return app_module.get_db_connection()


@pytest.fixture
def client(app_module):
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def admin_client(client):
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client
```

- [ ] **Step 3: Write a smoke test to confirm the fixtures work**

Create `python-backend/tests/test_smoke.py`:

```python
def test_login_page_loads(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_admin_login_works(admin_client):
    resp = admin_client.get("/admin")
    assert resp.status_code == 200


def test_default_employee_user_login_works(client):
    resp = client.post("/login", data={"username": "user", "password": "user123"})
    assert resp.status_code == 302
```

- [ ] **Step 4: Run the smoke tests**

Run: `cd python-backend && python3 -m pytest tests/test_smoke.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add python-backend/requirements.txt python-backend/tests/conftest.py python-backend/tests/test_smoke.py
git commit -m "test: add pytest infra for python-backend"
```

---

## Task 2: Database schema for employees, schedules, and attendance

**Files:**

- Modify: `python-backend/app.py` (inside `init_db()`)
- Create: `python-backend/tests/test_employee_schema.py`

- [ ] **Step 1: Write the failing test**

Create `python-backend/tests/test_employee_schema.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_employee_schema.py -v`
Expected: FAIL with `sqlite3.OperationalError: no such table: employees`

- [ ] **Step 3: Add the tables to `init_db()`**

In `python-backend/app.py`, find this exact block (the end of `init_db()`):

```python
    # Migrate any existing plain-text passwords to hashed
    all_users = conn.execute('SELECT id, password FROM users').fetchall()
    for u in all_users:
        if not u['password'].startswith('pbkdf2:') and not u['password'].startswith('scrypt:'):
            conn.execute(
                'UPDATE users SET password = ? WHERE id = ?',
                (generate_password_hash(u['password']), u['id'])
            )
    
    conn.commit()
    conn.close()
```

Replace it with (adds the three new tables right before the final commit):

```python
    # Migrate any existing plain-text passwords to hashed
    all_users = conn.execute('SELECT id, password FROM users').fetchall()
    for u in all_users:
        if not u['password'].startswith('pbkdf2:') and not u['password'].startswith('scrypt:'):
            conn.execute(
                'UPDATE users SET password = ? WHERE id = ?',
                (generate_password_hash(u['password']), u['id'])
            )

    # Empleados — roster, versioned pay schedules, and attendance
    conn.execute('''
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS employee_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        effective_from TEXT NOT NULL,
        scheduled_days TEXT NOT NULL,
        pay_amount REAL NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        work_date TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(employee_id, work_date)
    )
    ''')

    conn.commit()
    conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_employee_schema.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add python-backend/app.py python-backend/tests/test_employee_schema.py
git commit -m "feat: add employees, employee_schedules, attendance tables"
```

---

## Task 3: `get_week_bounds` helper

Pure function: given any date, return the Monday and Sunday of that calendar week.

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/tests/test_week_bounds.py`

- [ ] **Step 1: Write the failing test**

Create `python-backend/tests/test_week_bounds.py`:

```python
def test_get_week_bounds_midweek_date(app_module):
    start, end = app_module.get_week_bounds("2026-06-26")  # Friday
    assert start == "2026-06-22"
    assert end == "2026-06-28"


def test_get_week_bounds_on_monday(app_module):
    start, end = app_module.get_week_bounds("2026-06-22")
    assert start == "2026-06-22"
    assert end == "2026-06-28"


def test_get_week_bounds_on_sunday(app_module):
    start, end = app_module.get_week_bounds("2026-06-28")
    assert start == "2026-06-22"
    assert end == "2026-06-28"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_week_bounds.py -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'get_week_bounds'`

- [ ] **Step 3: Add the helper**

In `python-backend/app.py`, find this exact block (the line right after `init_db()` ends):

```python
    conn.commit()
    conn.close()

# Login decorator
def login_required(f):
```

Replace it with:

```python
    conn.commit()
    conn.close()


# ── Empleados y asistencia: helpers ───────────────────────────────────────────

def get_week_bounds(reference_date):
    """reference_date: 'YYYY-MM-DD'. Returns (monday, sunday) as 'YYYY-MM-DD' strings
    for the Mon-Sun week containing reference_date."""
    d = datetime.strptime(reference_date, '%Y-%m-%d')
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime('%Y-%m-%d'), sunday.strftime('%Y-%m-%d')


# Login decorator
def login_required(f):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_week_bounds.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add python-backend/app.py python-backend/tests/test_week_bounds.py
git commit -m "feat: add get_week_bounds helper"
```

---

## Task 4: `resolve_employee_schedule` helper

Looks up which `employee_schedules` row was in effect for a given week — the mechanism that makes edits apply to future weeks only.

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/tests/test_resolve_schedule.py`

- [ ] **Step 1: Write the failing test**

Create `python-backend/tests/test_resolve_schedule.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_resolve_schedule.py -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'resolve_employee_schedule'`

- [ ] **Step 3: Add the helper**

In `python-backend/app.py`, find:

```python
def get_week_bounds(reference_date):
    """reference_date: 'YYYY-MM-DD'. Returns (monday, sunday) as 'YYYY-MM-DD' strings
    for the Mon-Sun week containing reference_date."""
    d = datetime.strptime(reference_date, '%Y-%m-%d')
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime('%Y-%m-%d'), sunday.strftime('%Y-%m-%d')


# Login decorator
def login_required(f):
```

Replace it with:

```python
def get_week_bounds(reference_date):
    """reference_date: 'YYYY-MM-DD'. Returns (monday, sunday) as 'YYYY-MM-DD' strings
    for the Mon-Sun week containing reference_date."""
    d = datetime.strptime(reference_date, '%Y-%m-%d')
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime('%Y-%m-%d'), sunday.strftime('%Y-%m-%d')


def resolve_employee_schedule(conn, employee_id, week_start):
    """Returns the employee_schedules row in effect for the week starting on
    week_start ('YYYY-MM-DD', a Monday), or None if no version applies yet."""
    return conn.execute(
        '''SELECT * FROM employee_schedules
           WHERE employee_id = ? AND effective_from <= ?
           ORDER BY effective_from DESC LIMIT 1''',
        (employee_id, week_start)
    ).fetchone()


# Login decorator
def login_required(f):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_resolve_schedule.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add python-backend/app.py python-backend/tests/test_resolve_schedule.py
git commit -m "feat: add resolve_employee_schedule helper"
```

---

## Task 5: `compute_employee_pay` helper

The actual proration math: per-day rate × days marked present (any day counts, not just scheduled ones).

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/tests/test_compute_pay.py`

- [ ] **Step 1: Write the failing test**

Create `python-backend/tests/test_compute_pay.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_compute_pay.py -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'compute_employee_pay'`

- [ ] **Step 3: Add the helper**

In `python-backend/app.py`, find:

```python
def resolve_employee_schedule(conn, employee_id, week_start):
    """Returns the employee_schedules row in effect for the week starting on
    week_start ('YYYY-MM-DD', a Monday), or None if no version applies yet."""
    return conn.execute(
        '''SELECT * FROM employee_schedules
           WHERE employee_id = ? AND effective_from <= ?
           ORDER BY effective_from DESC LIMIT 1''',
        (employee_id, week_start)
    ).fetchone()


# Login decorator
def login_required(f):
```

Replace it with:

```python
def resolve_employee_schedule(conn, employee_id, week_start):
    """Returns the employee_schedules row in effect for the week starting on
    week_start ('YYYY-MM-DD', a Monday), or None if no version applies yet."""
    return conn.execute(
        '''SELECT * FROM employee_schedules
           WHERE employee_id = ? AND effective_from <= ?
           ORDER BY effective_from DESC LIMIT 1''',
        (employee_id, week_start)
    ).fetchone()


def compute_employee_pay(conn, employee_id, week_start, week_end):
    """Returns (total_pay, per_day_rate, days_worked, scheduled_days) for one
    employee for the Mon-Sun week [week_start, week_end]. Any day marked
    present counts toward pay, not only the employee's scheduled days."""
    schedule = resolve_employee_schedule(conn, employee_id, week_start)
    if schedule is None:
        return 0.0, 0.0, 0, []

    scheduled_days = [int(x) for x in schedule['scheduled_days'].split(',') if x != '']
    per_day_rate = (schedule['pay_amount'] / len(scheduled_days)) if scheduled_days else 0.0

    days_worked = conn.execute(
        'SELECT COUNT(*) FROM attendance WHERE employee_id = ? AND work_date BETWEEN ? AND ?',
        (employee_id, week_start, week_end)
    ).fetchone()[0]

    total_pay = round(per_day_rate * days_worked, 2)
    return total_pay, per_day_rate, days_worked, scheduled_days


# Login decorator
def login_required(f):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_compute_pay.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add python-backend/app.py python-backend/tests/test_compute_pay.py
git commit -m "feat: add compute_employee_pay helper"
```

---

## Task 6: `parse_scheduled_days` form helper

Turns the "days" checkboxes from a submitted form into a clean, validated CSV string.

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/tests/test_parse_scheduled_days.py`

- [ ] **Step 1: Write the failing test**

Create `python-backend/tests/test_parse_scheduled_days.py`:

```python
from werkzeug.datastructures import MultiDict


def test_parse_scheduled_days_dedupes_and_sorts(app_module):
    form = MultiDict([("days", "3"), ("days", "1"), ("days", "1")])
    assert app_module.parse_scheduled_days(form) == "1,3"


def test_parse_scheduled_days_ignores_invalid_values(app_module):
    form = MultiDict([("days", "7"), ("days", "-1"), ("days", "abc"), ("days", "2")])
    assert app_module.parse_scheduled_days(form) == "2"


def test_parse_scheduled_days_empty_when_nothing_selected(app_module):
    form = MultiDict([])
    assert app_module.parse_scheduled_days(form) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_parse_scheduled_days.py -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'parse_scheduled_days'`

- [ ] **Step 3: Add the helper**

In `python-backend/app.py`, find:

```python
    total_pay = round(per_day_rate * days_worked, 2)
    return total_pay, per_day_rate, days_worked, scheduled_days


# Login decorator
def login_required(f):
```

Replace it with:

```python
    total_pay = round(per_day_rate * days_worked, 2)
    return total_pay, per_day_rate, days_worked, scheduled_days


def parse_scheduled_days(form):
    """Reads the 'days' multi-value field from a submitted form and returns
    a sorted, deduped CSV string of valid weekday ints (0=Mon..6=Sun),
    or '' if nothing valid was selected."""
    raw = form.getlist('days')
    days = sorted({int(d) for d in raw if d.isdigit() and 0 <= int(d) <= 6})
    return ','.join(str(d) for d in days)


# Login decorator
def login_required(f):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_parse_scheduled_days.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add python-backend/app.py python-backend/tests/test_parse_scheduled_days.py
git commit -m "feat: add parse_scheduled_days form helper"
```

---

## Task 7: `POST /admin/employees/add` route

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/tests/test_route_add_employee.py`

- [ ] **Step 1: Write the failing tests**

Create `python-backend/tests/test_route_add_employee.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_route_add_employee.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Add the route**

In `python-backend/app.py`, find this exact block (end of `delete_user`):

```python
    conn = get_db_connection()
    user = conn.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
    if user:
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        flash(f'Usuario "{user["username"]}" eliminado.', 'success')
    return redirect(url_for('manage_users'))


# ── Promotions toggle ─────────────────────────────────────────────────────────
@app.route('/admin/promotions/add', methods=['POST'])
```

Replace it with:

```python
    conn = get_db_connection()
    user = conn.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
    if user:
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        flash(f'Usuario "{user["username"]}" eliminado.', 'success')
    return redirect(url_for('manage_users'))


# ── Empleados y asistencia ─────────────────────────────────────────────────────
@app.route('/admin/employees/add', methods=['POST'])
@login_required
@admin_required
def add_employee():
    name = request.form.get('name', '').strip()
    pay_amount_raw = request.form.get('pay_amount', '').strip()
    days_csv = parse_scheduled_days(request.form)

    if not name:
        flash('El nombre es requerido.', 'error')
        return redirect(url_for('employees_manage'))
    if not days_csv:
        flash('Selecciona al menos un día de la semana.', 'error')
        return redirect(url_for('employees_manage'))
    try:
        pay_amount = float(pay_amount_raw)
    except ValueError:
        pay_amount = 0
    if pay_amount <= 0:
        flash('El pago semanal debe ser mayor a 0.', 'error')
        return redirect(url_for('employees_manage'))

    conn = get_db_connection()
    cur = conn.execute('INSERT INTO employees (name) VALUES (?)', (name,))
    employee_id = cur.lastrowid
    week_start, _ = get_week_bounds(datetime.now().strftime('%Y-%m-%d'))
    conn.execute(
        'INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) '
        'VALUES (?, ?, ?, ?)',
        (employee_id, week_start, days_csv, pay_amount)
    )
    conn.commit()
    flash(f'Empleado "{name}" agregado.', 'success')
    return redirect(url_for('employees_manage'))


# ── Promotions toggle ─────────────────────────────────────────────────────────
@app.route('/admin/promotions/add', methods=['POST'])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_route_add_employee.py -v`
Expected: 4 passed

Note: this redirects to `employees_manage`, which doesn't exist as a route yet — that's fine, `url_for('employees_manage')` will raise a `BuildError` until Task 12 adds it. If Step 4 fails with `werkzeug.routing.exceptions.BuildError: Could not build url for endpoint 'employees_manage'`, that's expected at this point in the plan; re-run this same test after Task 12 is done to confirm it passes for real. To unblock Step 4 *right now*, temporarily change both `redirect(url_for('employees_manage'))` calls in `add_employee` to `redirect('/admin/employees/manage')`, run the test, then revert to `url_for('employees_manage')` once Task 12 adds that endpoint (Task 12, Step 3 will leave it as `url_for`).

- [ ] **Step 5: Commit**

```bash
git add python-backend/app.py python-backend/tests/test_route_add_employee.py
git commit -m "feat: add POST /admin/employees/add route"
```

---

## Task 8: `POST /admin/employees/update/<id>` route

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/tests/test_route_update_employee.py`

- [ ] **Step 1: Write the failing test**

Create `python-backend/tests/test_route_update_employee.py`:

```python
def test_update_employee_versions_schedule_for_next_week_only(admin_client, app_module):
    conn = app_module.get_db_connection()
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "pay_amount": "1000", "days": ["1", "2", "3"]},
    )
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]

    admin_client.post(
        f"/admin/employees/update/{employee_id}",
        data={"name": "Ana", "pay_amount": "1500", "days": ["4", "5", "6"]},
    )

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
    conn = app_module.get_db_connection()
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "pay_amount": "1000", "days": ["1"]},
    )
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]

    admin_client.post(
        f"/admin/employees/update/{employee_id}",
        data={"name": "Ana Maria", "pay_amount": "1000", "days": ["1"]},
    )

    employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    assert employee["name"] == "Ana Maria"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_route_update_employee.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Add the route**

In `python-backend/app.py`, find:

```python
    conn.commit()
    flash(f'Empleado "{name}" agregado.', 'success')
    return redirect(url_for('employees_manage'))


# ── Promotions toggle ─────────────────────────────────────────────────────────
```

Replace it with:

```python
    conn.commit()
    flash(f'Empleado "{name}" agregado.', 'success')
    return redirect(url_for('employees_manage'))


@app.route('/admin/employees/update/<int:employee_id>', methods=['POST'])
@login_required
@admin_required
def update_employee(employee_id):
    conn = get_db_connection()
    employee = conn.execute('SELECT * FROM employees WHERE id = ?', (employee_id,)).fetchone()
    if not employee:
        flash('Empleado no encontrado.', 'error')
        return redirect(url_for('employees_manage'))

    name = request.form.get('name', '').strip()
    pay_amount_raw = request.form.get('pay_amount', '').strip()
    days_csv = parse_scheduled_days(request.form)

    if not name:
        flash('El nombre es requerido.', 'error')
        return redirect(url_for('employees_manage'))
    if not days_csv:
        flash('Selecciona al menos un día de la semana.', 'error')
        return redirect(url_for('employees_manage'))
    try:
        pay_amount = float(pay_amount_raw)
    except ValueError:
        pay_amount = 0
    if pay_amount <= 0:
        flash('El pago semanal debe ser mayor a 0.', 'error')
        return redirect(url_for('employees_manage'))

    conn.execute('UPDATE employees SET name = ? WHERE id = ?', (name, employee_id))

    today_week_start, _ = get_week_bounds(datetime.now().strftime('%Y-%m-%d'))
    next_week_start = (
        datetime.strptime(today_week_start, '%Y-%m-%d') + timedelta(days=7)
    ).strftime('%Y-%m-%d')
    conn.execute(
        'INSERT INTO employee_schedules (employee_id, effective_from, scheduled_days, pay_amount) '
        'VALUES (?, ?, ?, ?)',
        (employee_id, next_week_start, days_csv, pay_amount)
    )
    conn.commit()
    flash(f'Empleado "{name}" actualizado. Los cambios de horario/pago aplican a partir de la próxima semana.', 'success')
    return redirect(url_for('employees_manage'))


# ── Promotions toggle ─────────────────────────────────────────────────────────
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_route_update_employee.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add python-backend/app.py python-backend/tests/test_route_update_employee.py
git commit -m "feat: add POST /admin/employees/update/<id> route, versions schedule for next week"
```

---

## Task 9: `POST /admin/employees/remove/<id>` route

Hard-deletes employees with no attendance history; soft-deactivates (keeps records) once any attendance exists.

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/tests/test_route_remove_employee.py`

- [ ] **Step 1: Write the failing tests**

Create `python-backend/tests/test_route_remove_employee.py`:

```python
def test_remove_employee_hard_deletes_when_no_attendance(admin_client, app_module):
    conn = app_module.get_db_connection()
    admin_client.post("/admin/employees/add", data={"name": "Ana", "pay_amount": "1000", "days": ["1"]})
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]

    admin_client.post(f"/admin/employees/remove/{employee_id}")

    assert conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone() is None
    assert conn.execute(
        "SELECT * FROM employee_schedules WHERE employee_id=?", (employee_id,)
    ).fetchone() is None


def test_remove_employee_deactivates_when_attendance_exists(admin_client, app_module):
    conn = app_module.get_db_connection()
    admin_client.post("/admin/employees/add", data={"name": "Ana", "pay_amount": "1000", "days": ["1"]})
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]
    conn.execute(
        "INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)", (employee_id, "2026-06-23")
    )
    conn.commit()

    admin_client.post(f"/admin/employees/remove/{employee_id}")

    employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    assert employee is not None
    assert employee["active"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_route_remove_employee.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Add the route**

In `python-backend/app.py`, find:

```python
    conn.commit()
    flash(f'Empleado "{name}" actualizado. Los cambios de horario/pago aplican a partir de la próxima semana.', 'success')
    return redirect(url_for('employees_manage'))


# ── Promotions toggle ─────────────────────────────────────────────────────────
```

Replace it with:

```python
    conn.commit()
    flash(f'Empleado "{name}" actualizado. Los cambios de horario/pago aplican a partir de la próxima semana.', 'success')
    return redirect(url_for('employees_manage'))


@app.route('/admin/employees/remove/<int:employee_id>', methods=['POST'])
@login_required
@admin_required
def remove_employee(employee_id):
    conn = get_db_connection()
    employee = conn.execute('SELECT * FROM employees WHERE id = ?', (employee_id,)).fetchone()
    if not employee:
        flash('Empleado no encontrado.', 'error')
        return redirect(url_for('employees_manage'))

    has_attendance = conn.execute(
        'SELECT COUNT(*) FROM attendance WHERE employee_id = ?', (employee_id,)
    ).fetchone()[0] > 0

    if has_attendance:
        conn.execute('UPDATE employees SET active = 0 WHERE id = ?', (employee_id,))
        conn.commit()
        flash(f'Empleado "{employee["name"]}" desactivado.', 'success')
    else:
        conn.execute('DELETE FROM employee_schedules WHERE employee_id = ?', (employee_id,))
        conn.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
        conn.commit()
        flash(f'Empleado "{employee["name"]}" eliminado.', 'success')
    return redirect(url_for('employees_manage'))


# ── Promotions toggle ─────────────────────────────────────────────────────────
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_route_remove_employee.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add python-backend/app.py python-backend/tests/test_route_remove_employee.py
git commit -m "feat: add POST /admin/employees/remove/<id> route"
```

---

## Task 10: `POST /admin/employees/attendance/toggle` route

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/tests/test_route_toggle_attendance.py`

- [ ] **Step 1: Write the failing test**

Create `python-backend/tests/test_route_toggle_attendance.py`:

```python
def test_toggle_attendance_marks_then_unmarks(admin_client, app_module):
    conn = app_module.get_db_connection()
    admin_client.post("/admin/employees/add", data={"name": "Ana", "pay_amount": "1000", "days": ["1"]})
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]

    admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": "2026-06-23", "week": "2026-06-22"},
    )
    present = conn.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?", (employee_id, "2026-06-23")
    ).fetchone()
    assert present is not None

    admin_client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": str(employee_id), "work_date": "2026-06-23", "week": "2026-06-22"},
    )
    gone = conn.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?", (employee_id, "2026-06-23")
    ).fetchone()
    assert gone is None


def test_toggle_attendance_requires_login(client):
    resp = client.post(
        "/admin/employees/attendance/toggle",
        data={"employee_id": "1", "work_date": "2026-06-23"},
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_route_toggle_attendance.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Add the route**

In `python-backend/app.py`, find:

```python
        conn.execute('DELETE FROM employee_schedules WHERE employee_id = ?', (employee_id,))
        conn.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
        conn.commit()
        flash(f'Empleado "{employee["name"]}" eliminado.', 'success')
    return redirect(url_for('employees_manage'))


# ── Promotions toggle ─────────────────────────────────────────────────────────
```

Replace it with:

```python
        conn.execute('DELETE FROM employee_schedules WHERE employee_id = ?', (employee_id,))
        conn.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
        conn.commit()
        flash(f'Empleado "{employee["name"]}" eliminado.', 'success')
    return redirect(url_for('employees_manage'))


@app.route('/admin/employees/attendance/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_attendance():
    employee_id = request.form.get('employee_id', '')
    work_date = request.form.get('work_date', '')
    week_param = request.form.get('week', '')

    if not employee_id.isdigit() or not work_date:
        flash('Solicitud inválida.', 'error')
        return redirect(url_for('employees_attendance'))

    conn = get_db_connection()
    existing = conn.execute(
        'SELECT id FROM attendance WHERE employee_id = ? AND work_date = ?',
        (employee_id, work_date)
    ).fetchone()
    if existing:
        conn.execute('DELETE FROM attendance WHERE id = ?', (existing['id'],))
    else:
        conn.execute(
            'INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)',
            (employee_id, work_date)
        )
    conn.commit()
    return redirect(url_for('employees_attendance', week=week_param or work_date))


# ── Promotions toggle ─────────────────────────────────────────────────────────
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_route_toggle_attendance.py -v`
Expected: 2 passed (this references `url_for('employees_attendance')`, added in Task 11 — if this runs before Task 11 exists you'll get a `BuildError`; re-run after Task 11 to confirm)

- [ ] **Step 5: Commit**

```bash
git add python-backend/app.py python-backend/tests/test_route_toggle_attendance.py
git commit -m "feat: add POST /admin/employees/attendance/toggle route"
```

---

## Task 11: `GET /admin/employees` (Asistencia view) + template

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/templates/employees.html`
- Create: `python-backend/tests/test_route_employees_attendance.py`

- [ ] **Step 1: Write the failing tests**

Create `python-backend/tests/test_route_employees_attendance.py`:

```python
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
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "pay_amount": "1000", "days": ["1", "2", "3"]},
    )
    employee_id = conn.execute("SELECT id FROM employees WHERE name='Ana'").fetchone()["id"]
    conn.execute(
        "INSERT INTO attendance (employee_id, work_date) VALUES (?, ?)", (employee_id, "2026-06-23")
    )
    conn.commit()

    resp = admin_client.get("/admin/employees?week=2026-06-22")
    assert resp.status_code == 200
    assert "333.33".encode("utf-8") in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_route_employees_attendance.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Add the route**

In `python-backend/app.py`, find:

```python
    conn.commit()
    return redirect(url_for('employees_attendance', week=week_param or work_date))


# ── Promotions toggle ─────────────────────────────────────────────────────────
```

Replace it with:

```python
    conn.commit()
    return redirect(url_for('employees_attendance', week=week_param or work_date))


@app.route('/admin/employees')
@login_required
@admin_required
def employees_attendance():
    week_param = request.args.get('week', '').strip()
    reference_date = week_param or datetime.now().strftime('%Y-%m-%d')
    try:
        week_start, week_end = get_week_bounds(reference_date)
    except ValueError:
        week_start, week_end = get_week_bounds(datetime.now().strftime('%Y-%m-%d'))

    conn = get_db_connection()
    employees = conn.execute('SELECT * FROM employees WHERE active = 1 ORDER BY name').fetchall()

    week_dates = [
        (datetime.strptime(week_start, '%Y-%m-%d') + timedelta(days=i)).strftime('%Y-%m-%d')
        for i in range(7)
    ]
    day_labels = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

    rows = []
    week_total = 0.0
    for emp in employees:
        schedule = resolve_employee_schedule(conn, emp['id'], week_start)
        scheduled_days = [int(x) for x in schedule['scheduled_days'].split(',')] if schedule else []
        total_pay, per_day_rate, days_worked, _ = compute_employee_pay(conn, emp['id'], week_start, week_end)
        present_dates = {
            r['work_date'] for r in conn.execute(
                'SELECT work_date FROM attendance WHERE employee_id = ? AND work_date BETWEEN ? AND ?',
                (emp['id'], week_start, week_end)
            ).fetchall()
        }
        days = [
            {
                'date': d,
                'label': day_labels[i],
                'scheduled': i in scheduled_days,
                'present': d in present_dates,
            }
            for i, d in enumerate(week_dates)
        ]
        rows.append({
            'id': emp['id'],
            'name': emp['name'],
            'days': days,
            'per_day_rate': per_day_rate,
            'days_worked': days_worked,
            'total_pay': total_pay,
        })
        week_total += total_pay

    prev_week = (datetime.strptime(week_start, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d')
    next_week = (datetime.strptime(week_start, '%Y-%m-%d') + timedelta(days=7)).strftime('%Y-%m-%d')

    return render_template(
        'employees.html',
        rows=rows,
        week_start=week_start,
        week_end=week_end,
        prev_week=prev_week,
        next_week=next_week,
        week_total=round(week_total, 2),
    )


# ── Promotions toggle ─────────────────────────────────────────────────────────
```

- [ ] **Step 4: Create the template**

Create `python-backend/templates/employees.html`:

```html
{% extends 'base.html' %} {% block title %}Asistencia — Empleados{% endblock %} {% block styles %}
<style>
  .emp-wrap {
    max-width: 900px;
    margin: 0 auto;
    padding: 24px 20px 60px;
  }
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
  }
  .page-title-txt {
    font-size: 1.8rem;
    font-weight: 800;
    color: #ff9800;
    margin: 0;
  }
  .back-btn {
    color: #aaa;
    text-decoration: none;
    font-size: 0.9rem;
    border: 1px solid #333;
    padding: 8px 16px;
    border-radius: 10px;
    background: #1e1e1e;
  }
  .back-btn:hover {
    border-color: #ff9800;
    color: #ff9800;
  }
  .alert {
    padding: 12px 16px;
    border-radius: 10px;
    margin-bottom: 16px;
    font-weight: 600;
    font-size: 0.9rem;
  }
  .alert-success {
    background: rgba(43, 138, 62, 0.2);
    color: #81c784;
    border: 1px solid rgba(43, 138, 62, 0.35);
  }
  .alert-error {
    background: rgba(231, 76, 60, 0.2);
    color: #ff8a80;
    border: 1px solid rgba(231, 76, 60, 0.35);
  }
  .period-tabs {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 24px;
  }
  .period-tab {
    padding: 8px 20px;
    border-radius: 20px;
    font-size: 0.9rem;
    font-weight: 600;
    text-decoration: none;
    border: 1px solid #333;
    color: #aaa;
    background: #1e1e1e;
    transition: all 0.15s;
  }
  .period-tab:hover {
    border-color: #ff9800;
    color: #ff9800;
  }
  .period-tab.active {
    background: #ff9800;
    color: #121212;
    border-color: #ff9800;
  }
  .week-nav {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }
  .week-nav-btn {
    color: #aaa;
    text-decoration: none;
    font-size: 0.9rem;
    border: 1px solid #333;
    padding: 8px 14px;
    border-radius: 10px;
    background: #1e1e1e;
  }
  .week-nav-btn:hover {
    border-color: #ff9800;
    color: #ff9800;
  }
  .week-label {
    font-weight: 700;
    color: #f5f5f5;
    font-size: 1rem;
  }
  .week-total-card {
    background: #1e1e1e;
    border: 2px solid #ff9800;
    border-radius: 16px;
    padding: 18px;
    text-align: center;
    margin-bottom: 28px;
  }
  .week-total-value {
    font-size: 2rem;
    font-weight: 800;
    color: #ff9800;
  }
  .week-total-label {
    font-size: 0.8rem;
    color: #aaa;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .emp-card {
    background: #1e1e1e;
    border-radius: 16px;
    border: 2px solid #2a2a2a;
    padding: 18px 20px;
    margin-bottom: 16px;
  }
  .emp-card-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 14px;
    flex-wrap: wrap;
    gap: 6px;
  }
  .emp-name {
    font-weight: 700;
    color: #f5f5f5;
    font-size: 1.05rem;
  }
  .emp-total {
    font-weight: 800;
    color: #ff9800;
    font-size: 1.1rem;
  }
  .day-row {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 8px;
  }
  .day-toggle-form {
    margin: 0;
  }
  .day-toggle-btn {
    width: 100%;
    padding: 10px 4px;
    border-radius: 10px;
    border: 1px solid #3d3d3d;
    background: #2d2d2d;
    color: #888;
    font-size: 0.78rem;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.15s;
  }
  .day-toggle-btn.scheduled {
    border-color: #555;
    color: #ccc;
  }
  .day-toggle-btn.present {
    background: #1b5e20;
    border-color: #2e7d32;
    color: #81c784;
  }
  .day-toggle-btn.scheduled.present {
    background: #ff9800;
    border-color: #ff9800;
    color: #121212;
  }
  .empty-state {
    text-align: center;
    color: #888;
    padding: 40px 20px;
  }
  @media (max-width: 520px) {
    .day-toggle-btn {
      padding: 8px 2px;
      font-size: 0.68rem;
    }
  }
</style>
{% endblock %} {% block body %}
<div class="emp-wrap">
  <div class="page-header">
    <h1 class="page-title-txt">💰 Empleados</h1>
    <a href="{{ url_for('admin_dashboard') }}" class="back-btn">← Panel</a>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %} {% if messages %}{% for cat, msg in messages %}
  <div class="alert alert-{{ cat }}">{{ msg }}</div>
  {% endfor %}{% endif %} {% endwith %}

  <div class="period-tabs">
    <a href="{{ url_for('employees_attendance') }}" class="period-tab active">Asistencia</a>
    <a href="{{ url_for('employees_manage') }}" class="period-tab">Gestionar empleados</a>
  </div>

  <div class="week-nav">
    <a href="{{ url_for('employees_attendance', week=prev_week) }}" class="week-nav-btn">← Semana anterior</a>
    <span class="week-label">{{ week_start }} – {{ week_end }}</span>
    <a href="{{ url_for('employees_attendance', week=next_week) }}" class="week-nav-btn">Semana siguiente →</a>
  </div>

  <div class="week-total-card">
    <div class="week-total-value">${{ "%.2f"|format(week_total) }}</div>
    <div class="week-total-label">Total a pagar esta semana</div>
  </div>

  {% if not rows %}
  <div class="empty-state">No hay empleados activos. Agrega uno en "Gestionar empleados".</div>
  {% endif %}

  {% for row in rows %}
  <div class="emp-card">
    <div class="emp-card-header">
      <div class="emp-name">{{ row.name }}</div>
      <div class="emp-total">${{ "%.2f"|format(row.total_pay) }} · {{ row.days_worked }} día(s)</div>
    </div>
    <div class="day-row">
      {% for day in row.days %}
      <form method="POST" action="{{ url_for('toggle_attendance') }}" class="day-toggle-form">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
        <input type="hidden" name="employee_id" value="{{ row.id }}" />
        <input type="hidden" name="work_date" value="{{ day.date }}" />
        <input type="hidden" name="week" value="{{ week_start }}" />
        <button
          type="submit"
          class="day-toggle-btn {% if day.scheduled %}scheduled{% endif %} {% if day.present %}present{% endif %}"
        >
          {{ day.label }}
        </button>
      </form>
      {% endfor %}
    </div>
  </div>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_route_employees_attendance.py -v`
Expected: 3 passed

- [ ] **Step 6: Re-run the toggle-attendance test from Task 10 to confirm its `url_for` now resolves**

Run: `cd python-backend && python3 -m pytest tests/test_route_toggle_attendance.py -v`
Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add python-backend/app.py python-backend/templates/employees.html python-backend/tests/test_route_employees_attendance.py
git commit -m "feat: add Asistencia view (GET /admin/employees) with day toggles and week totals"
```

---

## Task 12: `GET /admin/employees/manage` (Gestionar empleados view) + template

**Files:**

- Modify: `python-backend/app.py`
- Create: `python-backend/templates/employees_manage.html`
- Create: `python-backend/tests/test_route_employees_manage.py`

- [ ] **Step 1: Write the failing tests**

Create `python-backend/tests/test_route_employees_manage.py`:

```python
def test_employees_manage_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin/employees/manage")
    assert resp.status_code == 200
    assert "Gestionar empleados".encode("utf-8") in resp.data


def test_employees_manage_lists_added_employee(admin_client):
    admin_client.post(
        "/admin/employees/add",
        data={"name": "Ana", "pay_amount": "1000", "days": ["1", "2", "3"]},
    )
    resp = admin_client.get("/admin/employees/manage")
    assert "Ana".encode("utf-8") in resp.data


def test_employees_manage_blocks_non_admin(client):
    client.post("/login", data={"username": "user", "password": "user123"})
    resp = client.get("/admin/employees/manage")
    assert resp.status_code == 302
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_route_employees_manage.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Add the route**

In `python-backend/app.py`, find:

```python
    return render_template(
        'employees.html',
        rows=rows,
        week_start=week_start,
        week_end=week_end,
        prev_week=prev_week,
        next_week=next_week,
        week_total=round(week_total, 2),
    )


# ── Promotions toggle ─────────────────────────────────────────────────────────
```

Replace it with:

```python
    return render_template(
        'employees.html',
        rows=rows,
        week_start=week_start,
        week_end=week_end,
        prev_week=prev_week,
        next_week=next_week,
        week_total=round(week_total, 2),
    )


@app.route('/admin/employees/manage')
@login_required
@admin_required
def employees_manage():
    conn = get_db_connection()
    today_week_start, _ = get_week_bounds(datetime.now().strftime('%Y-%m-%d'))
    employees = conn.execute('SELECT * FROM employees ORDER BY active DESC, name').fetchall()

    day_labels = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
    rows = []
    for emp in employees:
        schedule = resolve_employee_schedule(conn, emp['id'], today_week_start)
        scheduled_days = [int(x) for x in schedule['scheduled_days'].split(',')] if schedule else []
        pay_amount = schedule['pay_amount'] if schedule else 0
        per_day_rate = (pay_amount / len(scheduled_days)) if scheduled_days else 0
        has_attendance = conn.execute(
            'SELECT COUNT(*) FROM attendance WHERE employee_id = ?', (emp['id'],)
        ).fetchone()[0] > 0
        rows.append({
            'id': emp['id'],
            'name': emp['name'],
            'active': emp['active'],
            'scheduled_days': scheduled_days,
            'pay_amount': pay_amount,
            'per_day_rate': per_day_rate,
            'has_attendance': has_attendance,
        })

    return render_template('employees_manage.html', rows=rows, day_labels=day_labels)


# ── Promotions toggle ─────────────────────────────────────────────────────────
```

- [ ] **Step 4: Create the template**

Create `python-backend/templates/employees_manage.html`:

```html
{% extends 'base.html' %} {% block title %}Gestionar empleados{% endblock %} {% block styles %}
<style>
  .emp-wrap {
    max-width: 900px;
    margin: 0 auto;
    padding: 24px 20px 60px;
  }
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
  }
  .page-title-txt {
    font-size: 1.8rem;
    font-weight: 800;
    color: #ff9800;
    margin: 0;
  }
  .back-btn {
    color: #aaa;
    text-decoration: none;
    font-size: 0.9rem;
    border: 1px solid #333;
    padding: 8px 16px;
    border-radius: 10px;
    background: #1e1e1e;
  }
  .back-btn:hover {
    border-color: #ff9800;
    color: #ff9800;
  }
  .alert {
    padding: 12px 16px;
    border-radius: 10px;
    margin-bottom: 16px;
    font-weight: 600;
    font-size: 0.9rem;
  }
  .alert-success {
    background: rgba(43, 138, 62, 0.2);
    color: #81c784;
    border: 1px solid rgba(43, 138, 62, 0.35);
  }
  .alert-error {
    background: rgba(231, 76, 60, 0.2);
    color: #ff8a80;
    border: 1px solid rgba(231, 76, 60, 0.35);
  }
  .period-tabs {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 28px;
  }
  .period-tab {
    padding: 8px 20px;
    border-radius: 20px;
    font-size: 0.9rem;
    font-weight: 600;
    text-decoration: none;
    border: 1px solid #333;
    color: #aaa;
    background: #1e1e1e;
    transition: all 0.15s;
  }
  .period-tab:hover {
    border-color: #ff9800;
    color: #ff9800;
  }
  .period-tab.active {
    background: #ff9800;
    color: #121212;
    border-color: #ff9800;
  }
  .section-heading {
    font-size: 0.78rem;
    font-weight: 700;
    color: #ff9800;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin: 0 0 12px;
  }
  .emp-roster-card {
    background: #1e1e1e;
    border-radius: 16px;
    border: 2px solid #2a2a2a;
    margin-bottom: 14px;
    overflow: hidden;
  }
  .emp-roster-card.inactive {
    opacity: 0.55;
  }
  .emp-roster-summary {
    padding: 16px 20px;
    cursor: pointer;
    list-style: none;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }
  .emp-roster-summary::-webkit-details-marker {
    display: none;
  }
  .emp-roster-name {
    font-weight: 700;
    color: #f5f5f5;
    font-size: 1rem;
  }
  .emp-roster-meta {
    font-size: 0.82rem;
    color: #aaa;
  }
  .inactive-badge {
    font-size: 0.7rem;
    font-weight: 700;
    color: #ff8a80;
    text-transform: uppercase;
    margin-left: 8px;
  }
  .emp-roster-body {
    padding: 0 20px 20px;
    border-top: 1px solid #2a2a2a;
  }
  .field-label {
    display: block;
    font-size: 0.78rem;
    color: #888;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 5px;
    margin-top: 14px;
  }
  .field-input {
    width: 100%;
    padding: 10px 12px;
    background: #2d2d2d;
    border: 1px solid #3d3d3d;
    border-radius: 10px;
    color: #f5f5f5;
    font-size: 0.95rem;
  }
  .field-input:focus {
    outline: none;
    border-color: #ff9800;
  }
  .day-checks {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 6px;
  }
  .day-check-label {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 6px 10px;
    border-radius: 8px;
    background: #2d2d2d;
    border: 1px solid #3d3d3d;
    font-size: 0.82rem;
    color: #ccc;
    cursor: pointer;
  }
  .save-hint {
    font-size: 0.78rem;
    color: #888;
    margin-top: 8px;
  }
  .form-actions {
    display: flex;
    gap: 10px;
    margin-top: 14px;
    flex-wrap: wrap;
  }
  .save-btn {
    padding: 10px 20px;
    background: #ff9800;
    color: #121212;
    border: none;
    border-radius: 10px;
    font-weight: 700;
    cursor: pointer;
  }
  .save-btn:hover {
    background: #e68900;
  }
  .danger-btn {
    padding: 10px 20px;
    background: #4a1f1f;
    color: #ff6b6b;
    border: none;
    border-radius: 10px;
    font-weight: 700;
    cursor: pointer;
  }
  .danger-btn:hover {
    background: #5a2f2f;
  }
  .add-card {
    background: #1e1e1e;
    border-radius: 16px;
    border: 2px solid #2a2a2a;
    padding: 20px 24px;
    margin-top: 32px;
  }
  .add-btn {
    width: 100%;
    padding: 12px;
    background: #ff9800;
    color: #121212;
    border: none;
    border-radius: 12px;
    font-size: 1rem;
    font-weight: 800;
    cursor: pointer;
    margin-top: 14px;
  }
  .add-btn:hover {
    background: #e68900;
  }
  .empty-state {
    text-align: center;
    color: #888;
    padding: 40px 20px;
  }
</style>
{% endblock %} {% block body %}
<div class="emp-wrap">
  <div class="page-header">
    <h1 class="page-title-txt">💰 Empleados</h1>
    <a href="{{ url_for('admin_dashboard') }}" class="back-btn">← Panel</a>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %} {% if messages %}{% for cat, msg in messages %}
  <div class="alert alert-{{ cat }}">{{ msg }}</div>
  {% endfor %}{% endif %} {% endwith %}

  <div class="period-tabs">
    <a href="{{ url_for('employees_attendance') }}" class="period-tab">Asistencia</a>
    <a href="{{ url_for('employees_manage') }}" class="period-tab active">Gestionar empleados</a>
  </div>

  <div class="section-heading">Empleados</div>

  {% if not rows %}
  <div class="empty-state">Todavía no hay empleados. Agrega uno abajo.</div>
  {% endif %}

  {% for row in rows %}
  <details class="emp-roster-card {% if not row.active %}inactive{% endif %}">
    <summary class="emp-roster-summary">
      <span>
        <span class="emp-roster-name">{{ row.name }}</span>
        {% if not row.active %}<span class="inactive-badge">Desactivado</span>{% endif %}
      </span>
      <span class="emp-roster-meta">
        {% for d in row.scheduled_days %}{{ day_labels[d] }}{% if not loop.last %}/{% endif %}{% endfor %}
        · ${{ "%.2f"|format(row.pay_amount) }}/sem · ${{ "%.2f"|format(row.per_day_rate) }}/día
      </span>
    </summary>
    <div class="emp-roster-body">
      <form method="POST" action="{{ url_for('update_employee', employee_id=row.id) }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
        <label class="field-label">Nombre</label>
        <input type="text" name="name" class="field-input" value="{{ row.name }}" required maxlength="60" />

        <label class="field-label">Días programados</label>
        <div class="day-checks">
          {% for d in range(7) %}
          <label class="day-check-label">
            <input type="checkbox" name="days" value="{{ d }}" {% if d in row.scheduled_days %}checked{% endif %} />
            {{ day_labels[d] }}
          </label>
          {% endfor %}
        </div>

        <label class="field-label">Pago semanal ($)</label>
        <input
          type="number"
          name="pay_amount"
          class="field-input"
          value="{{ row.pay_amount }}"
          min="1"
          step="0.01"
          required
        />

        <div class="save-hint">Los cambios de horario y pago aplican a partir de la próxima semana.</div>
        <div class="form-actions">
          <button type="submit" class="save-btn">Guardar cambios</button>
        </div>
      </form>

      <form
        method="POST"
        action="{{ url_for('remove_employee', employee_id=row.id) }}"
        class="form-actions"
        data-confirm="{% if row.has_attendance %}¿Desactivar a {{ row.name }}?{% else %}¿Eliminar a {{ row.name }}?{% endif %}"
      >
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
        <button type="submit" class="danger-btn">{% if row.has_attendance %}Desactivar{% else %}Eliminar{% endif %}</button>
      </form>
    </div>
  </details>
  {% endfor %}

  <div class="add-card">
    <div class="section-heading">Agregar empleado</div>
    <form method="POST" action="{{ url_for('add_employee') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
      <label class="field-label">Nombre</label>
      <input type="text" name="name" class="field-input" placeholder="Nombre del empleado" required maxlength="60" />

      <label class="field-label">Días programados</label>
      <div class="day-checks">
        {% for d in range(7) %}
        <label class="day-check-label">
          <input type="checkbox" name="days" value="{{ d }}" />
          {{ day_labels[d] }}
        </label>
        {% endfor %}
      </div>

      <label class="field-label">Pago semanal ($)</label>
      <input type="number" name="pay_amount" class="field-input" placeholder="1000" min="1" step="0.01" required />

      <button type="submit" class="add-btn">+ Agregar empleado</button>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_route_employees_manage.py -v`
Expected: 3 passed

- [ ] **Step 6: Re-run the full new test suite to confirm every cross-reference between routes resolves**

Run: `cd python-backend && python3 -m pytest tests/ -v`
Expected: all tests pass (this is the first time every route referenced by `url_for` in earlier tasks actually exists)

- [ ] **Step 7: Commit**

```bash
git add python-backend/app.py python-backend/templates/employees_manage.html python-backend/tests/test_route_employees_manage.py
git commit -m "feat: add Gestionar empleados view (GET /admin/employees/manage)"
```

---

## Task 13: Dashboard nav-card

**Files:**

- Modify: `python-backend/templates/admin_dashboard.html`
- Modify: `python-backend/tests/test_route_employees_attendance.py` (add one more test)

- [ ] **Step 1: Write the failing test**

In `python-backend/tests/test_route_employees_attendance.py`, append:

```python


def test_admin_dashboard_links_to_employees(admin_client):
    resp = admin_client.get("/admin")
    assert b"/admin/employees" in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python-backend && python3 -m pytest tests/test_route_employees_attendance.py::test_admin_dashboard_links_to_employees -v`
Expected: FAIL (link not present yet)

- [ ] **Step 3: Add the nav-card**

In `python-backend/templates/admin_dashboard.html`, find:

```html
    <a href="{{ url_for('manage_users') }}" class="nav-card">
      <div class="nav-card-icon">👥</div>
      <div class="nav-card-name">Usuarios</div>
      <div class="nav-card-desc">Cuentas y accesos</div>
    </a>
  </div>
```

Replace it with:

```html
    <a href="{{ url_for('manage_users') }}" class="nav-card">
      <div class="nav-card-icon">👥</div>
      <div class="nav-card-name">Usuarios</div>
      <div class="nav-card-desc">Cuentas y accesos</div>
    </a>
    <a href="{{ url_for('employees_attendance') }}" class="nav-card">
      <div class="nav-card-icon">💰</div>
      <div class="nav-card-name">Empleados</div>
      <div class="nav-card-desc">Asistencia y pagos</div>
    </a>
  </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python-backend && python3 -m pytest tests/test_route_employees_attendance.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the entire test suite one more time**

Run: `cd python-backend && python3 -m pytest tests/ -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add python-backend/templates/admin_dashboard.html python-backend/tests/test_route_employees_attendance.py
git commit -m "feat: link Empleados from the admin dashboard"
```

---

## Task 14: Manual verification in the running app

Automated tests cover the logic and routes; this step confirms the actual UI works end-to-end, per project convention of checking real behavior before calling a UI feature done.

**Files:** none (manual only)

- [ ] **Step 1: Start the Flask dev server**

```bash
cd python-backend && python3 app.py
```

Expected: server starts on port 5001 (or `$PORT`) without errors. Leave it running.

- [ ] **Step 2: Log in as admin**

Open `http://localhost:5001/login` in a browser, log in with `admin` / `admin123`.

- [ ] **Step 3: Walk through "Gestionar empleados"**

From the admin dashboard, click the new "💰 Empleados" card → click "Gestionar empleados" tab. Add an employee, e.g. name "Luisa", days Tue/Wed/Thu, pay 1000. Confirm it appears in the roster list with the correct days and a computed per-day rate (~$333.33).

- [ ] **Step 4: Walk through "Asistencia"**

Click the "Asistencia" tab. Confirm "Luisa" appears with 7 day-toggle buttons, Tue/Wed/Thu visually marked as scheduled. Click Tue and Wed to mark present. Confirm the employee's total updates to ~$666.67 and the week-total card reflects it. Click Tue again to unmark; confirm the total drops back to ~$333.33.

- [ ] **Step 5: Verify week navigation preserves history**

Click "← Semana anterior". Confirm the previous week shows zero attendance for Luisa (since she didn't exist then) without errors. Click "Semana siguiente →" twice to get back to the current week and confirm Wed is still marked present.

- [ ] **Step 6: Verify edits apply to future weeks only**

Go to "Gestionar empleados", edit Luisa: change pay to 1200 and days to Fri/Sat/Sun. Save. Go back to "Asistencia" for the current week — confirm Luisa still shows Tue/Wed/Thu scheduled and the original $1000/week rate (Wed still marked present, ~$333.33). Click "Semana siguiente →" — confirm next week shows Fri/Sat/Sun scheduled and the new $1200/week rate (~$400.00/day).

- [ ] **Step 7: Verify deactivate vs. delete**

In "Gestionar empleados", add a second employee "Test Temp" with no attendance ever marked — click "Eliminar" and confirm it disappears entirely. For Luisa (who has attendance), confirm the button reads "Desactivar" instead, click it, and confirm she moves to a dimmed "Desactivado" state in the roster but no longer appears on the "Asistencia" page.

- [ ] **Step 8: Stop the dev server**

`Ctrl+C` in the terminal running `app.py`.

---

## Self-review notes

- **Spec coverage:** per-day-rate-any-day-worked pay rule → Task 5; weekly auto-repeating schedule → `employee_schedules` + `resolve_employee_schedule` (Tasks 2–4); separate employee model from login `users` → `employees` table (Task 2); admin-only marking → `@admin_required` on every route (Tasks 7–12); kept history → versioned `employee_schedules` + week-navigable Asistencia view (Tasks 4, 11); future-weeks-only edits → `update_employee` writes `effective_from` = next Monday (Task 8); two-tab UX split → `employees.html` / `employees_manage.html` with shared `.period-tabs` (Tasks 11–12); dashboard entry point → Task 13. No spec requirement is without a task.
- **Placeholder scan:** none found — every step has runnable code.
- **Type/name consistency:** helper names (`get_week_bounds`, `resolve_employee_schedule`, `compute_employee_pay`, `parse_scheduled_days`) and route endpoint names (`employees_attendance`, `employees_manage`, `add_employee`, `update_employee`, `remove_employee`, `toggle_attendance`) are identical everywhere they're referenced, including across `url_for()` calls in templates and routes.
