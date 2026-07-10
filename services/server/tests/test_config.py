"""Tests for config secret validation and CORS header behaviour.

Run from services/server/:
    pytest tests/test_config.py -v
"""

import pytest

from project.config import REQUIRED_PRODUCTION_SECRETS, validate_required_config


def test_validate_required_config_is_noop_for_non_production(monkeypatch):
    for key in REQUIRED_PRODUCTION_SECRETS:
        monkeypatch.delenv(key, raising=False)
    # None of these should raise even with every secret unset.
    validate_required_config(None)
    validate_required_config("development")
    validate_required_config("testing")


def test_validate_required_config_raises_when_prod_secret_missing(monkeypatch):
    for key in REQUIRED_PRODUCTION_SECRETS:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        validate_required_config("production")
    message = str(excinfo.value)
    # every missing secret is named so ops knows exactly what to set
    for key in REQUIRED_PRODUCTION_SECRETS:
        assert key in message


def test_validate_required_config_passes_when_prod_secrets_present(monkeypatch):
    for key in REQUIRED_PRODUCTION_SECRETS:
        monkeypatch.setenv(key, "provided")
    validate_required_config("production")  # no raise


def test_cors_echoes_allowlisted_origin(client):
    # conftest sets CORS_ORIGIN=http://localhost:5173
    r = client.get("/api/ping", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"


def test_cors_does_not_echo_unknown_origin(client):
    r = client.get("/api/ping", headers={"Origin": "http://evil.example"})
    assert r.headers.get("Access-Control-Allow-Origin") != "http://evil.example"


def test_security_headers_present(client):
    r = client.get("/api/ping")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" in r.headers


def _login_sysadmin(app):
    from project import db
    from project.api.users.models import User

    u = User(email="cfg-admin@x.io", password="Passw0rd!", role="sysadmin", name="a")
    u.status = "active"
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post("/api/auth/login", json={"email": "cfg-admin@x.io", "password": "Passw0rd!"})
    return c


def test_mock_credit_rejected_when_disabled(app):
    """With ALLOW_MOCK_CREDIT off, a mock=true request is refused with 400
    before any mock data is generated."""
    app.config["ALLOW_MOCK_CREDIT"] = False
    c = _login_sysadmin(app)
    r = c.post("/api/credit-risk/kmv", json={"mock": True, "client_id": "C1"})
    assert r.status_code == 400
    assert "disabled" in r.get_json()["error"].lower()


def test_mock_credit_allowed_when_enabled(app):
    """With ALLOW_MOCK_CREDIT on, the request gets past the mock guard (it may
    still fail later for other reasons, but not with the 'disabled' message)."""
    app.config["ALLOW_MOCK_CREDIT"] = True
    c = _login_sysadmin(app)
    r = c.post("/api/credit-risk/kmv", json={"mock": True, "client_id": "C1"})
    body = r.get_json() or {}
    assert "disabled" not in str(body).lower()
