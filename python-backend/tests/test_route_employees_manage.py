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
