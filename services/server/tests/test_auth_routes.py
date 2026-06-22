def test_jwt_is_cookie_mode(app):
    assert app.config["JWT_TOKEN_LOCATION"] == ["cookies"]
    assert app.config["JWT_COOKIE_SAMESITE"] == "Strict"
    assert app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds() == 15 * 60
    assert app.config["JWT_REFRESH_TOKEN_EXPIRES"].total_seconds() == 12 * 60 * 60


def test_login_sets_cookies_and_returns_permissions(client, make_user):
    make_user("a@x.io", "analyst")
    resp = client.post(
        "/api/auth/login", json={"email": "a@x.io", "password": "Passw0rd!"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user"]["role"] == "analyst"
    assert "dataset:write" in body["permissions"]
    assert any("access_token_cookie" in h for h in resp.headers.getlist("Set-Cookie"))
    assert "Passw0rd" not in resp.get_data(as_text=True)


def test_login_bad_password_401(client, make_user):
    make_user("a@x.io", "analyst")
    resp = client.post(
        "/api/auth/login", json={"email": "a@x.io", "password": "wrong-pass1"}
    )
    assert resp.status_code == 401


def test_me_requires_session(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_identity_after_login(client, make_user):
    make_user("v@x.io", "viewer")
    client.post("/api/auth/login", json={"email": "v@x.io", "password": "Passw0rd!"})
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email"] == "v@x.io"
    assert "dataset:read" in resp.get_json()["permissions"]


def test_new_login_revokes_previous_session(client, make_user):
    make_user("u@x.io", "analyst")
    c1 = client
    c1.post("/api/auth/login", json={"email": "u@x.io", "password": "Passw0rd!"})
    c2 = c1.application.test_client()
    c2.post("/api/auth/login", json={"email": "u@x.io", "password": "Passw0rd!"})
    assert c1.get("/api/auth/me").status_code == 401
    assert c2.get("/api/auth/me").status_code == 200


def test_logout_revokes_session(client, make_user):
    make_user("u@x.io", "viewer")
    client.post("/api/auth/login", json={"email": "u@x.io", "password": "Passw0rd!"})
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
