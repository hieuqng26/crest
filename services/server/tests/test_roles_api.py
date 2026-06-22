def _login(client, make_user, role):
    make_user(f"{role}@x.io", role)
    client.post(
        "/api/auth/login", json={"email": f"{role}@x.io", "password": "Passw0rd!"}
    )


def test_viewer_cannot_read_roles(client, make_user):
    _login(client, make_user, "viewer")
    assert client.get("/api/roles/").status_code == 403


def test_sysadmin_lists_roles_with_user_counts(client, make_user):
    _login(client, make_user, "sysadmin")
    resp = client.get("/api/roles/")
    assert resp.status_code == 200
    names = {r["name"] for r in resp.get_json()}
    assert {"viewer", "analyst", "sysadmin"} <= names


def test_catalog_endpoint(client, make_user):
    _login(client, make_user, "sysadmin")
    resp = client.get("/api/roles/catalog")
    assert resp.status_code == 200
    assert any(p["key"] == "credit_risk" for p in resp.get_json()["pages"])


def test_create_role(client, make_user):
    _login(client, make_user, "sysadmin")
    resp = client.post(
        "/api/roles/",
        json={
            "name": "risk_lead",
            "description": "Risk lead",
            "permissions": ["dataset:read", "credit_risk:read", "credit_risk:execute"],
        },
    )
    assert resp.status_code == 201
    assert resp.get_json()["permissions"] == [
        "credit_risk:execute",
        "credit_risk:read",
        "dataset:read",
    ]


def test_create_role_rejects_wildcard(client, make_user):
    _login(client, make_user, "sysadmin")
    assert (
        client.post(
            "/api/roles/", json={"name": "god", "permissions": ["*"]}
        ).status_code
        == 400
    )


def test_create_role_rejects_unknown_permission(client, make_user):
    _login(client, make_user, "sysadmin")
    assert (
        client.post(
            "/api/roles/", json={"name": "x", "permissions": ["dataset:manage"]}
        ).status_code
        == 400
    )


def test_create_role_duplicate_name(client, make_user):
    _login(client, make_user, "sysadmin")
    assert (
        client.post(
            "/api/roles/", json={"name": "viewer", "permissions": []}
        ).status_code
        == 409
    )


def test_cannot_modify_system_role(client, make_user):
    _login(client, make_user, "sysadmin")
    assert (
        client.put(
            "/api/roles/sysadmin", json={"permissions": ["dataset:read"]}
        ).status_code
        == 403
    )
    assert client.delete("/api/roles/sysadmin").status_code == 403


def test_cannot_delete_role_in_use(client, make_user):
    _login(client, make_user, "sysadmin")
    make_user("someviewer@x.io", "viewer")
    resp = client.delete("/api/roles/viewer")
    assert resp.status_code == 409
    assert resp.get_json()["user_count"] >= 1


def test_update_role_permissions_takes_effect(client, make_user):
    _login(client, make_user, "sysadmin")
    client.post("/api/roles/", json={"name": "temp", "permissions": ["dataset:read"]})
    resp = client.put(
        "/api/roles/temp", json={"permissions": ["dataset:read", "dataset:write"]}
    )
    assert resp.status_code == 200
    assert "dataset:write" in resp.get_json()["permissions"]


def test_delete_unused_custom_role(client, make_user):
    _login(client, make_user, "sysadmin")
    client.post("/api/roles/", json={"name": "temp2", "permissions": ["dataset:read"]})
    assert client.delete("/api/roles/temp2").status_code == 200
