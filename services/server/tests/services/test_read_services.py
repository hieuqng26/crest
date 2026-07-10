"""Direct tests of the extracted read services.

Like test_launch_services.py, these call the transport-agnostic services the
way the MCP tools do — no Flask request — and double as the MCP read contract.
The HTTP routes exercise the same functions via the API integration tests.
"""

import json
from datetime import datetime, timezone

import pytest

from project.exceptions import ConflictError, NotFoundError


@pytest.fixture()
def seed(app, make_user):
    from project import db
    from project.db_models.calibration_models import (
        CalibrationRun,
        CalibrationRunLog,
        Dataset,
        ModelConfig,
    )

    user = make_user("reads@example.com", "sysadmin")
    ds = Dataset(
        name="cal-ds",
        source="upload",
        file_path="uploads/reads/data.csv",
        row_count=10,
        created_by=user.email,
        status="ready",
        kind="calibration",
    )
    cfg = ModelConfig(
        name="cfg",
        family="regression",
        algorithm="Ridge",
        hyperparams_json="{}",
        created_by=user.email,
    )
    db.session.add_all([ds, cfg])
    db.session.flush()
    run = CalibrationRun(
        run_id="reads-cal-1",
        status="success",
        dataset_id=ds.id,
        model_config_id=cfg.id,
        triggered_by=user.email,
        started_at=datetime.now(timezone.utc),
        val_metrics_json=json.dumps(
            {"r2": 0.9, "val_obs": {"actual": [1, 2]}, "train_obs": {}, "fitted": [1]}
        ),
    )
    db.session.add(run)
    db.session.flush()
    for n in range(3):
        db.session.add(
            CalibrationRunLog(
                run_id=run.run_id,
                logged_at=datetime.now(timezone.utc),
                level="info",
                message=f"line {n}",
            )
        )
    db.session.commit()
    return {"user": user, "dataset": ds, "cfg": cfg, "run": run}


# ── calibrations reads ──────────────────────────────────────────────────────
def test_calibrations_list_runs_envelope(app, seed):
    from project.services import calibrations as svc

    out = svc.list_runs(page=1, per_page=10)
    assert set(out) == {"items", "total", "page", "pages"}
    assert out["total"] == 1
    item = out["items"][0]
    assert item["config_name"] == "cfg"
    assert item["dataset_name"] == "cal-ds"


def test_calibrations_get_run_not_found(app, seed):
    from project.services import calibrations as svc

    with pytest.raises(NotFoundError):
        svc.get_run("nope")


def test_calibrations_diagnostics_full_vs_slim(app, seed):
    from project.services import calibrations as svc

    full = svc.get_diagnostics(seed["run"].run_id)  # HTTP default keeps val_obs
    assert "val_obs" in full["metrics"]
    slim = svc.get_diagnostics(seed["run"].run_id, slim=True)
    assert "val_obs" not in slim["metrics"]
    assert "train_obs" not in slim["metrics"]
    assert slim["metrics"]["fitted"] == [1]  # non-heavy arrays survive slimming


def test_calibrations_diagnostics_conflict_on_unfinished_run(app, seed):
    from project import db
    from project.services import calibrations as svc

    seed["run"].status = "running"
    db.session.commit()
    with pytest.raises(ConflictError):
        svc.get_diagnostics(seed["run"].run_id)


# ── run_logs ────────────────────────────────────────────────────────────────
def test_run_logs_cursor_pagination(app, seed):
    from datetime import datetime, timezone

    from project import db
    from project.db_models.calibration_models import CalibrationRunLog
    from project.services import run_logs as svc

    # Initial load tails the log: most recent `limit` lines, oldest→newest.
    first = svc.get_logs("calibration", seed["run"].run_id, limit=2)
    assert [log["message"] for log in first["logs"]] == ["line 1", "line 2"]
    assert first["has_more"] is True

    db.session.add(
        CalibrationRunLog(
            run_id=seed["run"].run_id,
            logged_at=datetime.now(timezone.utc),
            level="info",
            message="line 3",
        )
    )
    db.session.commit()
    rest = svc.get_logs(
        "calibration", seed["run"].run_id, after_id=first["next_after_id"]
    )
    assert [log["message"] for log in rest["logs"]] == ["line 3"]


def test_run_logs_unknown_run_404(app, seed):
    from project.services import run_logs as svc

    with pytest.raises(NotFoundError):
        svc.get_logs("forecast", "missing-run")


# ── credit_risk reads ───────────────────────────────────────────────────────
def test_credit_risk_get_run_active_resolution(app, seed):
    from project import db
    from project.db_models.credit_models import CreditRiskRun
    from project.services import credit_risk as svc

    with pytest.raises(NotFoundError):  # nothing active yet
        svc.get_run(None)

    cr = CreditRiskRun(
        run_id="reads-cr-1",
        dataset_id=seed["dataset"].id,
        is_active=True,
        exposure=1.0,
        discount_rate=0.05,
        lifetime_horizon=5,
        curve="moodys",
        status="success",
        triggered_by=seed["user"].email,
    )
    db.session.add(cr)
    db.session.commit()

    active = svc.get_run(None)
    assert active["run_id"] == "reads-cr-1"
    assert active["dataset_name"] == "cal-ds"
    assert active["client_ids"] == []


# ── refs reads ──────────────────────────────────────────────────────────────
def test_datasets_and_model_configs_lists(app, seed):
    from project.services import datasets as ds_svc
    from project.services import model_configs as cfg_svc

    assert [d["name"] for d in ds_svc.list_datasets(kind="calibration")] == ["cal-ds"]
    assert ds_svc.list_datasets(kind="forecast") == []

    configs = cfg_svc.list_configs()
    assert configs[0]["name"] == "cfg"
    # One (non-segmented) run references it.
    assert configs[0]["used_by"] == "1 run"


# ── workflows reads ─────────────────────────────────────────────────────────
def test_workflows_get_workflow_light_shape(app, seed):
    from project import db
    from project.constants import RunStatus, WorkflowStage
    from project.db_models.workflow_models import WorkflowRun
    from project.services import workflows as svc

    wf = WorkflowRun(
        run_id="reads-wf-1",
        name="wf",
        status=RunStatus.RUNNING,
        current_stage=WorkflowStage.TRAINING,
        triggered_by=seed["user"].email,
        calibration_dataset_id=seed["dataset"].id,
        forecast_dataset_id=seed["dataset"].id,
        targets_json="[]",
        analysis_params_json="{}",
    )
    db.session.add(wf)
    db.session.flush()
    seed["run"].workflow_run_id = wf.id
    db.session.commit()

    light = svc.get_workflow("reads-wf-1", light=True)
    assert light["run_id"] == "reads-wf-1"
    assert light["targets"][0]["calibration"]["run_id"] == seed["run"].run_id
    # Light payload stays lean: no metric blobs.
    assert "val_metrics_json" not in json.dumps(light)

    with pytest.raises(NotFoundError):
        svc.get_workflow("missing", light=True)
