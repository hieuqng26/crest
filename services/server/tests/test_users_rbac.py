def _login(client, make_user, role, email=None):
    email = email or f"{role}@x.io"
    make_user(email, role)
    client.post("/api/auth/login", json={"email": email, "password": "Passw0rd!"})


def test_viewer_cannot_list_users(client, make_user):
    _login(client, make_user, "viewer")
    assert client.get("/api/user/all").status_code == 403


def test_analyst_cannot_create_user(client, make_user):
    _login(client, make_user, "analyst")
    resp = client.post(
        "/api/user/add",
        json={"email": "new@x.io", "password": "Passw0rd!", "role": "viewer"},
    )
    assert resp.status_code == 403


def test_sysadmin_can_list_users(client, make_user):
    _login(client, make_user, "sysadmin")
    assert client.get("/api/user/all").status_code == 200


def test_invalid_role_rejected(client, make_user):
    _login(client, make_user, "sysadmin")
    make_user("t@x.io", "viewer")
    resp = client.put("/api/user/update/t@x.io", json={"role": "superuser"})
    assert resp.status_code == 400


def test_add_user_with_custom_role(client, make_user):
    _login(client, make_user, "sysadmin")
    client.post(
        "/api/roles/", json={"name": "risk_lead", "permissions": ["credit_risk:read"]}
    )
    resp = client.post(
        "/api/user/add",
        json={"email": "rl@x.io", "password": "Passw0rd!", "role": "risk_lead"},
    )
    assert resp.status_code == 201


def test_add_batch_rejects_invalid_role(client, make_user):
    _login(client, make_user, "sysadmin")
    resp = client.post(
        "/api/user/add_batch",
        json={
            "users": [
                {
                    "email": "ok@x.io",
                    "password": "Passw0rd!",
                    "role": "viewer",
                    "name": "Ok",
                },
                {
                    "email": "bad@x.io",
                    "password": "Passw0rd!",
                    "role": "nope",
                    "name": "Bad",
                },
            ]
        },
    )
    assert resp.status_code == 400
    assert "bad@x.io" in resp.get_data(as_text=True)
