"""audit v2.1.1 — Fix 2: importing an older-schema backup no longer bricks the app.

A backup from an older version can pass validation (has orders/users/menu_prices)
yet miss newer tables/columns (print_jobs, config, users.password_changed…).
Before the fix it was restored as-is and the next admin request 500'd until the
process restarted. Now init_db()'s migrations run right after the restore.
"""
import io
import os
import sqlite3


def _direct_conn():
    return sqlite3.connect(os.environ["RESTAURANT_DB_PATH"])


def _has_table(name):
    c = _direct_conn()
    try:
        row = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None
    finally:
        c.close()


def _build_stripped_backup(path):
    """A valid-but-old backup: only orders/users/menu_prices, with the columns
    init_db() relies on for its seeds. Missing print_jobs, config, employees, etc."""
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE orders (id TEXT PRIMARY KEY, items TEXT, total REAL, "
        "payment_method TEXT, amount_paid REAL, change_amount REAL, date TEXT, "
        "status TEXT, customer_name TEXT)"
    )
    c.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, "
        "password TEXT, role TEXT, created_at TEXT)"
    )
    c.execute("CREATE TABLE menu_prices (key TEXT PRIMARY KEY, label TEXT, price REAL)")
    c.commit()
    c.close()


def _import(admin_client, data):
    return admin_client.post(
        "/admin/respaldo/importar",
        data={"respaldo": (io.BytesIO(data), "old_backup.db")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )


def test_stripped_backup_is_accepted_and_schema_is_healed(admin_client, tmp_path):
    stripped_path = str(tmp_path / "stripped.db")
    _build_stripped_backup(stripped_path)
    with open(stripped_path, "rb") as f:
        stripped_bytes = f.read()

    # The stripped backup lacks these; they must not exist as a precondition
    # guarantee only after we confirm the import ran, so just import now.
    resp = _import(admin_client, stripped_bytes)
    assert resp.status_code == 302  # accepted (valid backup), session cleared

    # Missing tables/columns must exist after the import thanks to init_db().
    assert _has_table("print_jobs")
    assert _has_table("config")
    assert _has_table("employees")
    assert _has_table("activity_log")

    c = _direct_conn()
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()}
    finally:
        c.close()
    assert "password_changed" in cols


def test_admin_dashboard_works_after_stripped_import(admin_client, tmp_path):
    stripped_path = str(tmp_path / "stripped.db")
    _build_stripped_backup(stripped_path)
    with open(stripped_path, "rb") as f:
        stripped_bytes = f.read()

    resp = _import(admin_client, stripped_bytes)
    assert resp.status_code == 302

    # Import clears the session; init_db() reseeds the default admin (admin/admin123).
    admin_client.post("/login", data={"username": "admin", "password": "admin123"})

    # /admin queries print_jobs, config and users.password_changed — the exact
    # things a stripped backup lacked. A 200 proves the schema was healed.
    resp = admin_client.get("/admin")
    assert resp.status_code == 200
