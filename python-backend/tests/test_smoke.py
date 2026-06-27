def test_login_page_loads(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_admin_login_works(admin_client):
    resp = admin_client.get("/admin")
    assert resp.status_code == 200


def test_default_employee_user_login_works(client):
    resp = client.post("/login", data={"username": "user", "password": "user123"})
    assert resp.status_code == 302
