"""Direct tests of the launch service layer.

These call the transport-agnostic services the way the future MCP tools will —
no Flask request/response — and assert they raise the right DomainError on bad
input. They double as the MCP contract tests for run-launching.

Run from services/server/:
    pytest tests/services/test_launch_services.py -v
"""

import json
from unittest.mock import patch

import pytest

from project.exceptions import (
    BadRequestError,
    NotFoundError,
    UnprocessableEntityError,
)


@pytest.fixture()
def seed(app, make_user):
    from project import db
    from project.db_models.calibration_models import Dataset, ModelConfig

    user = make_user("svc@example.com", "sysadmin")
    ds = Dataset(
        name="cal-ds",
        source="upload",
        file_path="uploads/svc/data.csv",
        row_count=10,
        created_by=user.email,
        status="ready",
        kind="calibration",
    )
    cfg = ModelConfig(
        name="cfg",
        family="regression",
        algorithm="ElasticNet",
        hyperparams_json="{}",
        train_split=0.8,
        created_by=user.email,
    )
    db.session.add_all([ds, cfg])
    db.session.commit()
    return {"user": user, "dataset": ds, "cfg": cfg}


# ── calibrations.create_run ────────────────────────────────────────────────
def test_calibration_create_run_missing_dataset_raises_not_found(app, seed):
    from project.schemas.calibrations import CreateCalibrationRun
    from project.services import calibrations as svc

    payload = CreateCalibrationRun(dataset_id=999999, model_config_id=seed["cfg"].id)
    with pytest.raises(NotFoundError):
        svc.create_run(payload, seed["user"].email)


def test_calibration_create_run_missing_config_raises_not_found(app, seed):
    from project.schemas.calibrations import CreateCalibrationRun
    from project.services import calibrations as svc

    payload = CreateCalibrationRun(
        dataset_id=seed["dataset"].id, model_config_id=999999
    )
    with pytest.raises(NotFoundError):
        svc.create_run(payload, seed["user"].email)


def test_calibration_create_run_dispatches_on_success(app, seed):
    from project.schemas.calibrations import CreateCalibrationRun
    from project.services import calibrations as svc

    payload = CreateCalibrationRun(
        dataset_id=seed["dataset"].id, model_config_id=seed["cfg"].id
    )
    with patch("project.services.calibrations.run_calibration.delay") as delay:
        result = svc.create_run(payload, seed["user"].email)
    assert result["status"] == "queued"
    delay.assert_called_once_with(result["run_id"])


# ── forecast_runs.create_run ───────────────────────────────────────────────
def test_forecast_create_run_missing_calibration_raises_not_found(app, seed):
    from project.schemas.forecast_runs import CreateForecastRun
    from project.services import forecast_runs as svc

    payload = CreateForecastRun(
        calibration_run_id="does-not-exist", dataset_id=seed["dataset"].id
    )
    with pytest.raises(NotFoundError):
        svc.create_run(payload, seed["user"].email)


def test_forecast_create_run_rejects_unsuccessful_calibration(app, seed):
    from project import db
    from project.db_models.calibration_models import CalibrationRun
    from project.schemas.forecast_runs import CreateForecastRun
    from project.services import forecast_runs as svc

    cal = CalibrationRun(
        run_id="cal-not-done",
        status="running",
        target_col="x",
        dataset_id=seed["dataset"].id,
        model_config_id=seed["cfg"].id,
        triggered_by=seed["user"].email,
    )
    db.session.add(cal)
    db.session.commit()

    payload = CreateForecastRun(
        calibration_run_id="cal-not-done", dataset_id=seed["dataset"].id
    )
    with pytest.raises(BadRequestError):
        svc.create_run(payload, seed["user"].email)


# ── workflows.create_workflow ──────────────────────────────────────────────
def test_workflow_create_missing_config_raises_not_found(app, seed):
    from project.schemas.workflows import CreateWorkflow
    from project.services import workflows as svc

    payload = CreateWorkflow(
        name="wf",
        model_config_id=999999,
        targets=[{"target_col": "total_assets"}],
    )
    with pytest.raises(NotFoundError):
        svc.create_workflow(payload, seed["user"].email)


def test_workflow_create_missing_calibration_dataset_raises_422(app, seed):
    from project import db
    from project.schemas.workflows import CreateWorkflow
    from project.services import workflows as svc

    # Remove the only calibration dataset so the launch is unprocessable.
    db.session.delete(seed["dataset"])
    db.session.commit()

    payload = CreateWorkflow(
        name="wf",
        model_config_id=seed["cfg"].id,
        targets=[{"target_col": "total_assets"}],
    )
    with pytest.raises(UnprocessableEntityError):
        svc.create_workflow(payload, seed["user"].email)


# ── workflows.rerun_workflow ───────────────────────────────────────────────
def test_rerun_workflow_preserves_segmentation(app, seed):
    """A segmented workflow must relaunch segmented. Segmentation lives on the
    child CalibrationRun rows (WorkflowRun has no seg columns), so the rerun has
    to recover it from the original children — otherwise the re-run calibrations
    are non-segmented and every downstream sector/segment view disappears."""
    from project import db
    from project.constants import RunStatus, WorkflowStage
    from project.db_models.calibration_models import CalibrationRun, Dataset
    from project.db_models.workflow_models import WorkflowRun
    from project.services import workflows as svc

    user, cfg, cal_ds = seed["user"], seed["cfg"], seed["dataset"]
    # rerun reuses the latest 'forecast' dataset — seed only has calibration.
    fc_ds = Dataset(
        name="fc-ds",
        source="upload",
        file_path="uploads/svc/fc.csv",
        row_count=10,
        created_by=user.email,
        status="ready",
        kind="forecast",
    )
    db.session.add(fc_ds)
    db.session.commit()

    wf = WorkflowRun(
        run_id="wf-seg",
        name="seg wf",
        status=RunStatus.SUCCESS,
        current_stage=WorkflowStage.DONE,
        triggered_by=user.email,
        calibration_dataset_id=cal_ds.id,
        forecast_dataset_id=fc_ds.id,
        targets_json=json.dumps(
            [
                {
                    "target_col": "total_assets",
                    "model_config_id": cfg.id,
                    "feature_cols": ["gdp"],
                }
            ]
        ),
        analysis_params_json=json.dumps(
            {
                "exposure": 1.0,
                "discount_rate": 0.05,
                "lifetime_horizon": 5,
                "curve": "baseline",
            }
        ),
    )
    db.session.add(wf)
    db.session.flush()

    seg_sectors = json.dumps(["Energy", "Financials"])
    seg_overrides = json.dumps({"Energy": {"max_segments": 2}})
    orig_cal = CalibrationRun(
        run_id="wf-seg-cal",
        name="seg wf · total_assets",
        dataset_id=cal_ds.id,
        model_config_id=cfg.id,
        status=RunStatus.SUCCESS,
        triggered_by=user.email,
        target_col="total_assets",
        feature_cols_json=json.dumps(["gdp"]),
        seg_sectors_json=seg_sectors,
        seg_split_by="subsector",
        seg_max_segments=3,
        seg_sector_overrides_json=seg_overrides,
        workflow_run_id=wf.id,
    )
    db.session.add(orig_cal)
    db.session.commit()

    with patch("project.services.workflows.run_calibration.delay"):
        result = svc.rerun_workflow("wf-seg", user.email)

    new_run_id = result["targets"][0]["calibration_run_id"]
    new_cal = CalibrationRun.query.filter_by(run_id=new_run_id).first()
    assert new_cal.seg_sectors_json == seg_sectors
    assert new_cal.seg_split_by == "subsector"
    assert new_cal.seg_max_segments == 3
    assert new_cal.seg_sector_overrides_json == seg_overrides
