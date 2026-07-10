"""Tests for the request-guarding redesign (Pydantic strict schemas, body-size
cap, rate limiting, /query hardening) — the replacement for the removed
``validate_request`` regex WAF.

Run from services/server/:
    pytest tests/test_request_validation.py -v
"""

import pytest


def _sysadmin(app, email="rv-admin@x.io"):
    from project import db
    from project.api.users.models import User

    u = User(email=email, password="Passw0rd!", role="sysadmin", name="a")
    u.status = "active"
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post("/api/auth/login", json={"email": email, "password": "Passw0rd!"})
    return c


# ── strict Pydantic (replaces the WAF's key/char/length checks) ────────────
def test_add_user_rejects_unknown_key(app):
    c = _sysadmin(app)
    r = c.post(
        "/api/user/add",
        json={"email": "a@x.io", "password": "Passw0rd!", "role": "viewer", "junk": 1},
    )
    assert r.status_code == 400
    assert "message" in r.get_json()  # extra="forbid" -> unknown key rejected


def test_add_user_rejects_oversized_name(app):
    c = _sysadmin(app)
    r = c.post(
        "/api/user/add",
        json={
            "email": "b@x.io",
            "password": "Passw0rd!",
            "role": "viewer",
            "name": "x" * 40,  # > 32
        },
    )
    assert r.status_code == 400
    assert "name" in r.get_json()["message"]


def test_add_user_accepts_accented_name(app):
    """The WAF's char allowlist rejected accented/non-Latin names; strict
    schemas don't — a legitimate international name is now accepted."""
    c = _sysadmin(app)
    r = c.post(
        "/api/user/add",
        json={
            "email": "jose@x.io",
            "password": "Passw0rd!",
            "role": "viewer",
            "name": "José Ñoño",
        },
    )
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["name"] == "José Ñoño"


def test_login_rejects_unknown_key(app):
    r = app.test_client().post(
        "/api/auth/login", json={"email": "x@x.io", "password": "p", "extra": 1}
    )
    assert r.status_code == 400
    assert "message" in r.get_json()


# ── global body-size cap ───────────────────────────────────────────────────
def test_oversized_body_returns_413(app):
    app.config["MAX_CONTENT_LENGTH"] = 200  # bytes
    # login has no broad try/except, so the RequestEntityTooLarge propagates to
    # the boundary and surfaces as 413.
    r = app.test_client().post(
        "/api/auth/login", json={"email": "c@x.io", "password": "x" * 5000}
    )
    assert r.status_code == 413


# ── auth rate limiting ─────────────────────────────────────────────────────
def test_login_rate_limited_returns_429(app):
    from project.extensions import limiter

    # The @limiter.limit callable reads RATELIMIT_AUTH per request, so lowering
    # it here throttles /login; reset() clears the shared memory counter.
    limiter.reset()
    app.config["RATELIMIT_AUTH"] = "2 per minute"
    try:
        c = app.test_client()
        codes = [
            c.post(
                "/api/auth/login", json={"email": "n@x.io", "password": "bad"}
            ).status_code
            for _ in range(4)
        ]
        assert 429 in codes  # limit is 2/min -> the 3rd+ attempt is throttled
    finally:
        limiter.reset()


# ── /query hardening (read-only DB login is the real boundary) ─────────────
def test_query_rejects_non_select(app):
    c = _sysadmin(app)
    r = c.post("/api/datasets/query", json={"sql": "DROP TABLE users"})
    assert r.status_code == 400
    assert "SELECT" in r.get_json()["error"]


def test_query_requires_configured_risk_db(app, monkeypatch):
    monkeypatch.delenv("RISK_DB_CONN_STR", raising=False)
    c = _sysadmin(app)
    r = c.post("/api/datasets/query", json={"sql": "SELECT 1"})
    assert r.status_code == 503


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
