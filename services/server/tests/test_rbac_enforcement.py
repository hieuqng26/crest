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


def test_require_perm_requires_auth(probe_app):
    resp = probe_app.test_client().post("/api/probe/exec")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Endpoint permission matrix
# (method, path, viewer_status, analyst_status)
#
# Legend for expected status codes:
#   200/204 — past RBAC, handler returned success
#   400/404/409 — past RBAC, handler rejected bad/missing data
#   403 — RBAC denied before reaching the handler
# ---------------------------------------------------------------------------
MATRIX = [
    # datasets — viewer:read, analyst:read+write
    ("get", "/api/datasets/", 200, 200),
    ("post", "/api/datasets/upload", 403, 400),  # 400 = past RBAC, no file
    # credit_risk — viewer:read, analyst:read+write+execute
    ("post", "/api/credit-risk/runs", 403, 400),  # 400 = past RBAC, bad body
    # auditlog — neither viewer nor analyst has auditlog:read
    ("post", "/api/log/all", 403, 403),
    # model_configs — both have model_config:read; write is analyst-only
    ("get", "/api/model-configs/", 200, 200),
    ("post", "/api/model-configs/", 403, 400),  # 400 = past RBAC, missing fields
    # calibrations — both have calibration:read; execute is analyst-only
    ("get", "/api/calibrations/", 200, 200),
    ("post", "/api/calibrations/", 403, 400),  # 400 = past RBAC, missing fields
    # forecasts (forecast_runs) — both have forecast:read; execute is analyst-only
    ("get", "/api/forecast-runs", 200, 200),
    ("post", "/api/forecast-runs", 403, 400),  # 400 = past RBAC, missing fields
    # evaluations — both viewer and analyst have evaluation:read
    # 404 = past RBAC, run not found (expected for non-existent id)
    ("get", "/api/evaluations/nonexistent-run", 404, 404),
]


def _login_as(app, email, role):
    from project import db
    from project.api.users.models import User

    u = User(email=email, password="Passw0rd!", role=role, name=email)
    u.status = "active"
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post("/api/auth/login", json={"email": email, "password": "Passw0rd!"})
    return c


@pytest.mark.parametrize("method,path,viewer_status,analyst_status", MATRIX)
def test_endpoint_matrix(app, method, path, viewer_status, analyst_status):
    cv = _login_as(app, "mv@x.io", "viewer")
    assert getattr(cv, method)(path).status_code == viewer_status
    ca = _login_as(app, "ma@x.io", "analyst")
    assert getattr(ca, method)(path).status_code == analyst_status
