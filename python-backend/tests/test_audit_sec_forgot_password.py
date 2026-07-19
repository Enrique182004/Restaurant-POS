"""audit v2.1.1 — Fix 1: /forgot_password no longer resets any password without auth.

Previously an unauthenticated POST could reset ANY account (admin included).
Combined with the 0.0.0.0 bind, anyone on the LAN could take over admin.
The endpoint is now gated behind @login_required + @admin_required.
"""
import os
import sqlite3

from werkzeug.security import check_password_hash


def _direct_conn():
    return sqlite3.connect(os.environ["RESTAURANT_DB_PATH"])


def _password_hash(username):
    c = _direct_conn()
    try:
        return c.execute("SELECT password FROM users WHERE username = ?", (username,)).fetchone()[0]
    finally:
        c.close()


def test_unauthenticated_forgot_password_does_not_change_admin_password(client):
    before = _password_hash("admin")

    resp = client.post(
        "/forgot_password",
        data={"username": "admin", "new_password": "hacked123", "confirm_password": "hacked123"},
    )

    # login_required kicks unauthenticated callers back to /login, no reset happens.
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    after = _password_hash("admin")
    assert after == before
    assert not check_password_hash(after, "hacked123")


def test_non_admin_cannot_reset_via_forgot_password(client, app_module):
    # 'user' is a seeded non-admin account.
    client.post("/login", data={"username": "user", "password": "user123"})
    before = _password_hash("admin")

    resp = client.post(
        "/forgot_password",
        data={"username": "admin", "new_password": "hacked123", "confirm_password": "hacked123"},
    )
    # admin_required redirects non-admins to home, no reset happens.
    assert resp.status_code == 302

    after = _password_hash("admin")
    assert after == before
    assert not check_password_hash(after, "hacked123")


def test_admin_can_still_reset_via_forgot_password(admin_client):
    resp = admin_client.post(
        "/forgot_password",
        data={"username": "user", "new_password": "brandnew1", "confirm_password": "brandnew1"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    after = _password_hash("user")
    assert check_password_hash(after, "brandnew1")
