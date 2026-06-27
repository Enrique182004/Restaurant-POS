# Employee Attendance & Payroll — Design Spec

Date: 2026-06-26
Status: Approved, ready for implementation plan

## Problem

The admin/owner needs to track which employees work which days and how much
each gets paid per week, with the ability to change an employee's schedule
and pay amount going forward without disturbing past records.

Example from the request: one employee works Tue/Wed/Thu for 1000 MXN/week;
another works Fri/Sat/Sun for 1000 MXN/week. If the first employee only
shows up 2 of their 3 scheduled days in a given week, pay should be
prorated automatically rather than paid in full.

## Decisions from brainstorming

- **Pay rule**: per-day rate, any day worked. `per_day_rate = pay_amount /
scheduled_days_count`. Weekly pay = `per_day_rate × days actually marked
present that week`, counting _any_ day marked present (not only the
  employee's scheduled days — covering an extra shift pays the same rate).
- **Pay period**: weekly, Monday–Sunday, auto-repeating indefinitely from a
  standing per-employee schedule (no manual re-setup each week).
- **Employee model**: a new, separate concept from the existing `users`
  login table. Payroll employees do not need POS login accounts.
- **Who marks attendance**: admin-role accounts only (`@admin_required`,
  matching the existing pattern for Usuarios/Inventario/Reportes).
- **History**: kept permanently. Every past week's attendance and computed
  pay must remain viewable per employee.
- **Edit timing**: changing an employee's scheduled days or pay amount only
  affects **future weeks**. The current week and all past weeks keep using
  whatever schedule/pay was in effect when those days were marked.
- **UX**: one new dashboard entry point ("💰 Empleados"), split into two
  focused sub-views reached by a segmented tab control (reusing the
  `.period-tabs` pattern already used in `reports.html`):
  - **Asistencia** (default tab) — daily-use view: week selector + per-day
    toggles + computed totals. No edit/add forms here.
  - **Gestionar empleados** (second tab) — roster view: add/edit/deactivate
    employees and their schedule/pay. No attendance grid here.

## Data model

Three new SQLite tables (raw SQL via `sqlite3`, matching existing
`init_db()` style — no ORM is used in this codebase).

```sql
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employee_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    effective_from TEXT NOT NULL,   -- ISO date, always a Monday
    scheduled_days TEXT NOT NULL,   -- CSV of weekday ints, 0=Mon .. 6=Sun
    pay_amount REAL NOT NULL,       -- flat weekly amount for full schedule
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    work_date TEXT NOT NULL,        -- ISO date
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(employee_id, work_date)
);
```

### Versioned schedule/pay (how "future weeks only" works)

`employee_schedules` is append-only. Each row is valid starting
`effective_from` (a Monday) until superseded by a later row.

- **New employee**: insert one schedule row with `effective_from` = the
  Monday of the current week → applies immediately.
- **Editing an existing employee's days or pay**: insert a **new** row with
  `effective_from` = Monday of _next_ week. Existing rows are never
  modified or deleted.
- **Resolving the rule for any given week** (`week_start` = that week's
  Monday):
  ```sql
  SELECT * FROM employee_schedules
  WHERE employee_id = ? AND effective_from <= ?
  ORDER BY effective_from DESC LIMIT 1
  ```

This makes past/current weeks immune to later edits with no extra
snapshot bookkeeping — the lookup just picks whichever version was active
at that time.

### Attendance

A row's existence in `attendance` means the employee was present that day.
Marking present = `INSERT OR IGNORE`. Unmarking = `DELETE`. Toggling any
day within the week being viewed is allowed (not restricted to today).

### Pay computation for one employee, one week

```python
week_start, week_end = monday, sunday  # for the viewed week
schedule = resolve_schedule(employee_id, week_start)  # query above
scheduled_days = schedule['scheduled_days'].split(',')   # e.g. ['1','2','3']
per_day_rate = schedule['pay_amount'] / len(scheduled_days)

days_worked = count of attendance rows for employee_id
              where work_date between week_start and week_end

total_pay = round(per_day_rate * days_worked, 2)
```

Guard: an employee must have at least 1 scheduled day (validated on
add/edit) to avoid division by zero.

## Routes

All routes use `@login_required @admin_required`, CSRF-protected forms,
flash messages, and the existing dark/orange template style — matching
`manage_users` / `users.html` conventions.

| Method | Route                                | Purpose                                                                                                                                                                                                                                              |
| ------ | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/admin/employees`                   | Asistencia tab. Query param `week=YYYY-MM-DD` (any date in the target week; defaults to today). Shows active employees, that week's per-day toggles, computed totals, week total.                                                                    |
| GET    | `/admin/employees/manage`            | Gestionar empleados tab. Lists employees with current schedule/pay, edit and deactivate controls, add-employee form.                                                                                                                                 |
| POST   | `/admin/employees/add`               | Create employee + initial schedule row (`effective_from` = current Monday). Validates name, ≥1 scheduled day, pay_amount > 0.                                                                                                                        |
| POST   | `/admin/employees/update/<id>`       | Insert new schedule row (`effective_from` = next Monday) and/or update `employees.name`. Flash explains the change starts next week.                                                                                                                 |
| POST   | `/admin/employees/deactivate/<id>`   | Set `active = 0`. Used instead of delete once an employee has any attendance history. If an employee has zero attendance rows, allow a real `DELETE` instead (button label "Eliminar" vs "Desactivar" chosen server-side based on history presence). |
| POST   | `/admin/employees/attendance/toggle` | Params: `employee_id`, `work_date`. Toggles the attendance row (insert if absent, delete if present) for that single date.                                                                                                                           |

## UI

- **Dashboard** (`admin_dashboard.html`): one new `.nav-card` "💰 Empleados"
  in the existing `.nav-grid`, linking to `/admin/employees`.
- **`employees.html`** (Asistencia, default view):
  - Segmented tabs at top: "Asistencia" (active) / "Gestionar empleados",
    styled like `.period-tabs` in `reports.html`.
  - Week navigation: ◀ / ▶ arrows + date range label (e.g. "23–29 jun
    2026"), defaulting to the current week.
  - Week-total summary card at top (sum of all employees' pay for the
    viewed week).
  - One row per active employee: name, Mon–Sun toggle buttons (scheduled
    days visually distinguished — e.g. outlined — from off-schedule days,
    but every day is clickable), and that employee's computed total for
    the viewed week, updated live after each toggle (via a small fetch +
    DOM update, or full page reload — reload is acceptable and simpler,
    consistent with the rest of the app which is not SPA-style).
- **`employees_manage.html`** (Gestionar empleados view):
  - Same tabs at top, "Gestionar empleados" active.
  - One card per employee (active first, deactivated below, dimmed):
    name, current scheduled days + weekly pay + computed per-day rate,
    "Editar" (reveals inline form: name, Mon–Sun checkboxes, pay amount —
    note: "Los cambios aplican a partir de la próxima semana"), and
    Desactivar/Eliminar per the rule above.
  - "+ Agregar empleado" form at the bottom: name, Mon–Sun checkboxes,
    weekly pay amount — same visual pattern as the "Agregar usuario" form
    in `users.html`.
- Currency formatting matches the rest of the app: `$` + `"%.2f"|format(...)`.

## Out of scope

- No payroll "closing" / marking a week as paid — this is a record of
  hours/pay, not a payment-processing or accounting export feature.
- No employee login/auth — purely an attendance/pay roster.
- No overtime rules, taxes, or deductions beyond the day-proration
  described above.
