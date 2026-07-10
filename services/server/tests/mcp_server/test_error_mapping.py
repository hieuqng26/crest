"""The tool_boundary contract: DomainError → coded ToolError, everything else
→ generic message (no internals leak), mirroring api/error_handlers.py."""

import pytest
from mcp.server.fastmcp.exceptions import ToolError


def test_not_found_maps_to_coded_tool_error(mcp_app):
    from project.mcp_server.tools.runs import crest_get_calibration_run

    with pytest.raises(ToolError, match=r"\[not_found\]"):
        crest_get_calibration_run("no-such-run")


def test_bad_request_maps_to_coded_tool_error(mcp_app):
    from project.mcp_server.tools.runs import crest_get_run_logs

    with pytest.raises(ToolError, match=r"\[bad_request\]"):
        crest_get_run_logs("nonsense-type", "some-run")


def test_conflict_maps_to_coded_tool_error(mcp_app, make_user):
    from project import db
    from project.db_models.calibration_models import (
        CalibrationRun,
        Dataset,
        ModelConfig,
    )
    from project.mcp_server.tools.results import crest_get_calibration_diagnostics

    user = make_user("mcp-conflict@example.com", "sysadmin")
    ds = Dataset(
        name="d",
        source="upload",
        file_path="uploads/x.csv",
        row_count=1,
        created_by=user.email,
        status="ready",
        kind="calibration",
    )
    cfg = ModelConfig(
        name="c",
        family="regression",
        algorithm="Ridge",
        hyperparams_json="{}",
        created_by=user.email,
    )
    db.session.add_all([ds, cfg])
    db.session.flush()
    run = CalibrationRun(
        run_id="running-run",
        status="running",
        dataset_id=ds.id,
        model_config_id=cfg.id,
        triggered_by=user.email,
    )
    db.session.add(run)
    db.session.commit()

    with pytest.raises(ToolError, match=r"\[conflict\]"):
        crest_get_calibration_diagnostics("running-run")


def test_unexpected_exception_is_not_leaked(mcp_app, monkeypatch):
    from project.mcp_server.tools import runs as runs_module

    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(runs_module.calibration_service, "get_run", boom)

    with pytest.raises(ToolError) as exc_info:
        runs_module.crest_get_calibration_run("whatever")
    assert str(exc_info.value) == "Internal server error"
    assert "secret" not in str(exc_info.value)


def test_conflict_dependencies_are_included(mcp_app, monkeypatch):
    from project.exceptions import ConflictError
    from project.mcp_server.tools import runs as runs_module

    def blocked(*args, **kwargs):
        raise ConflictError("Cannot delete", dependencies={"forecast_runs": 2})

    monkeypatch.setattr(runs_module.calibration_service, "get_run", blocked)

    with pytest.raises(ToolError, match="forecast_runs"):
        runs_module.crest_get_calibration_run("whatever")
