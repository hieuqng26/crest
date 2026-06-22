import pytest
from flask import Blueprint, jsonify

from project.api.auth.decorators import require_perm


@pytest.fixture()
def probe_app(app):
    bp = Blueprint("probe", __name__)

    @bp.post("/probe/exec")
    @require_perm("credit_risk:execute")
    def _exec():
        return jsonify(ok=True)

    app.register_blueprint(bp, url_prefix="/api")
    return app


@pytest.mark.xfail(reason="needs login from Task 7")
@pytest.mark.parametrize(
    "role,status", [("viewer", 403), ("analyst", 200), ("sysadmin", 200)]
)
def test_require_perm_gates_by_role(probe_app, make_user, role, status):
    client = probe_app.test_client()
    make_user(f"{role}@x.io", role)
    client.post(
        "/api/auth/login", json={"email": f"{role}@x.io", "password": "Passw0rd!"}
    )
    resp = client.post("/api/probe/exec")
    assert resp.status_code == status


@pytest.mark.xfail(reason="needs login from Task 7")
def test_require_perm_requires_auth(probe_app):
    resp = probe_app.test_client().post("/api/probe/exec")
    assert resp.status_code == 401
