"""Launch tools end-to-end against the service layer (Celery mocked) —
mirrors tests/services/test_launch_services.py through the MCP transport."""

from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError


@pytest.fixture()
def seed(mcp_app, make_user):
    from project import db
    from project.db_models.calibration_models import Dataset, ModelConfig

    user = make_user("mcp@example.com", "sysadmin")
    ds = Dataset(
        name="cal-ds",
        source="upload",
        file_path="uploads/mcp/data.csv",
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
    return {"user": user, "dataset_id": ds.id, "cfg_id": cfg.id}


def test_create_calibration_run_queues_and_records_mcp_identity(seed):
    from project.db_models.calibration_models import CalibrationRun
    from project.mcp_server.tools.launch import crest_create_calibration_run
    from project.schemas.calibrations import CreateCalibrationRun

    params = CreateCalibrationRun(
        dataset_id=seed["dataset_id"], model_config_id=seed["cfg_id"]
    )
    with patch("project.services.calibrations.run_calibration.delay") as delay:
        result = crest_create_calibration_run(params)

    assert result["status"] == "queued"
    delay.assert_called_once_with(result["run_id"])
    run = CalibrationRun.query.filter_by(run_id=result["run_id"]).first()
    assert run.triggered_by == "mcp-agent"  # MCP_IDENTITY default
    # MCP launches are tagged AUTO in job history; the manual wizard is MANUAL.
    assert run.origin == "auto"
    assert result["origin"] == "auto"


def test_create_calibration_run_missing_dataset_is_not_found(seed):
    from project.mcp_server.tools.launch import crest_create_calibration_run
    from project.schemas.calibrations import CreateCalibrationRun

    params = CreateCalibrationRun(dataset_id=999999, model_config_id=seed["cfg_id"])
    with pytest.raises(ToolError, match=r"\[not_found\]"):
        crest_create_calibration_run(params)


def test_create_forecast_run_rejects_unfinished_calibration(seed):
    from project import db
    from project.db_models.calibration_models import CalibrationRun
    from project.mcp_server.tools.launch import crest_create_forecast_run
    from project.schemas.forecast_runs import CreateForecastRun

    cal = CalibrationRun(
        run_id="mcp-cal-running",
        status="running",
        dataset_id=seed["dataset_id"],
        model_config_id=seed["cfg_id"],
        triggered_by=seed["user"].email,
    )
    db.session.add(cal)
    db.session.commit()

    params = CreateForecastRun(
        calibration_run_id="mcp-cal-running", dataset_id=seed["dataset_id"]
    )
    with pytest.raises(ToolError, match=r"\[bad_request\]"):
        crest_create_forecast_run(params)
