import os

import pytest

os.environ["CONFIG_NAME"] = "testing"
os.environ.setdefault("CORS_ORIGIN", "http://localhost:5173")


@pytest.fixture()
def app():
    from project import cache, create_app, db
    from project.api.roles.defaults import ensure_default_roles

    app = create_app()
    app.config.update(TESTING=True, JWT_COOKIE_CSRF_PROTECT=False, JWT_COOKIE_SECURE=False)
    with app.app_context():
        db.create_all()
        ensure_default_roles()
        cache.clear()  # role registry + login-lockout keys must not leak between tests
        yield app
        db.session.remove()
        db.drop_all()
        cache.clear()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_user(app):
    from project import db
    from project.api.users.models import User

    def _make(email, role, password="Passw0rd!"):
        u = User(email=email, password=password, role=role, name=email)
        u.status = "active"
        db.session.add(u)
        db.session.commit()
        return u

    return _make


@pytest.fixture()
def login(client):
    def _login(email, password="Passw0rd!"):
        return client.post("/api/auth/login", json={"email": email, "password": password})

    return _login
