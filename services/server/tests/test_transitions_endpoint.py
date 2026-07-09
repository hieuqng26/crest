"""Endpoint tests for GET /api/credit-risk/analysis/transitions."""

import json

from project import db
from project.db_models.credit_models import CreditRiskResult, CreditRiskRun


def _login_as(app, email, role="sysadmin"):
    from project.api.users.models import User

    u = User(email=email, password="Passw0rd!", role=role, name=email)
    u.status = "active"
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post("/api/auth/login", json={"email": email, "password": "Passw0rd!"})
    return c


def _kmv(scenario, path):
    return [{"YEAR": y, "SCENARIO": scenario, "Rating": r} for y, r in path]


def _seed_run(run_id="tr-run", active=True, status="success"):
    cr = CreditRiskRun(
        run_id=run_id,
        dataset_id=1,
        is_active=active,
        exposure=1.0,
        discount_rate=0.05,
        lifetime_horizon=5,
        curve="moodys",
        status=status,
    )
    db.session.add(cr)
    db.session.add(
        CreditRiskResult(
            run_id=run_id,
            client_id="C1",
            kmv_json=json.dumps(_kmv("Baseline", [(2024, "Baa1"), (2025, "Baa2")])),
        )
    )
    db.session.add(
        CreditRiskResult(
            run_id=run_id,
            client_id="C2",
            kmv_json=json.dumps(_kmv("Baseline", [(2024, "Baa1"), (2025, "Baa1")])),
        )
    )
    db.session.commit()
    return cr


def test_active_run_returns_matrix(app):
    with app.app_context():
        _seed_run()
        c = _login_as(app, "cr1@x.io")
        resp = c.get("/api/credit-risk/analysis/transitions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["scenario"] == "Baseline"
        assert data["scenarios"] == ["Baseline"]
        assert data["ratings"] == ["Baa1", "Baa2"]
        # From Baa1: 2 obs (->Baa2, ->Baa1) => 50/50.
        assert data["matrix"][0] == [50.0, 50.0]
        assert data["row_totals"][0] == 2
        assert data["n_clients"] == 2


def test_unknown_scenario_returns_422(app):
    with app.app_context():
        _seed_run()
        c = _login_as(app, "cr2@x.io")
        resp = c.get("/api/credit-risk/analysis/transitions?scenario=Nope")
        assert resp.status_code == 422


def test_no_active_run_returns_404(app):
    with app.app_context():
        c = _login_as(app, "cr3@x.io")
        resp = c.get("/api/credit-risk/analysis/transitions")
        assert resp.status_code == 404
