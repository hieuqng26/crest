"""Read tools: pagination envelopes, log cursoring, and the per-call
app-context handling (including from a non-main thread)."""

import threading
from datetime import datetime, timezone

import pytest


@pytest.fixture()
def seeded_runs(mcp_app, make_user):
    from project import db
    from project.db_models.calibration_models import (
        CalibrationRun,
        CalibrationRunLog,
        Dataset,
        ModelConfig,
    )

    user = make_user("mcp-read@example.com", "sysadmin")
    ds = Dataset(
        name="cal-ds",
        source="upload",
        file_path="uploads/mcp/read.csv",
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

    runs = []
    for i in range(3):
        run = CalibrationRun(
            run_id=f"mcp-read-{i}",
            status="success" if i else "failed",
            dataset_id=ds.id,
            model_config_id=cfg.id,
            triggered_by=user.email,
            started_at=datetime.now(timezone.utc),
        )
        db.session.add(run)
        runs.append(run)
    db.session.flush()
    for n in range(5):
        db.session.add(
            CalibrationRunLog(
                run_id="mcp-read-0",
                logged_at=datetime.now(timezone.utc),
                level="info",
                message=f"line {n}",
            )
        )
    db.session.commit()
    return {"dataset": ds, "cfg": cfg, "runs": runs}


def test_list_calibration_runs_envelope_and_paging(seeded_runs):
    from project.mcp_server.tools.runs import crest_list_calibration_runs

    out = crest_list_calibration_runs(page=1, per_page=2)
    assert set(out) == {"items", "total", "page", "pages"}
    assert out["total"] == 3
    assert out["pages"] == 2
    assert len(out["items"]) == 2
    assert {"config_name", "dataset_name", "algorithm"} <= set(out["items"][0])

    filtered = crest_list_calibration_runs(status="failed")
    assert filtered["total"] == 1
    assert filtered["items"][0]["run_id"] == "mcp-read-0"


def test_get_run_logs_cursoring(seeded_runs):
    from datetime import datetime, timezone

    from project import db
    from project.db_models.calibration_models import CalibrationRunLog
    from project.mcp_server.tools.runs import crest_get_run_logs

    # Initial load tails the log: the most recent `limit` lines, oldest→newest
    # within the page.
    first = crest_get_run_logs("calibration", "mcp-read-0", limit=3)
    assert [log["message"] for log in first["logs"]] == ["line 2", "line 3", "line 4"]
    ids = [log["id"] for log in first["logs"]]
    assert ids == sorted(ids)
    assert first["next_after_id"] == ids[-1]

    # Polling: a fresh line appears; the cursor fetches only that line.
    db.session.add(
        CalibrationRunLog(
            run_id="mcp-read-0",
            logged_at=datetime.now(timezone.utc),
            level="info",
            message="fresh",
        )
    )
    db.session.commit()
    rest = crest_get_run_logs(
        "calibration", "mcp-read-0", after_id=first["next_after_id"], limit=3
    )
    assert [log["message"] for log in rest["logs"]] == ["fresh"]
    assert rest["has_more"] is False


def test_list_datasets_and_configs(seeded_runs):
    from project.mcp_server.tools.refs import (
        crest_list_datasets,
        crest_list_model_configs,
    )

    datasets = crest_list_datasets(kind="calibration")
    assert [d["name"] for d in datasets] == ["cal-ds"]
    configs = crest_list_model_configs()
    assert configs[0]["name"] == "cfg"
    assert "used_by" in configs[0]


def test_diagnostics_slims_heavy_arrays(seeded_runs):
    import json

    from project import db
    from project.mcp_server.tools.results import crest_get_calibration_diagnostics

    run = seeded_runs["runs"][1]
    run.val_metrics_json = json.dumps(
        {"r2": 0.9, "val_obs": {"actual": [1] * 1000}, "residuals": [0.1]}
    )
    db.session.commit()

    out = crest_get_calibration_diagnostics(run.run_id)
    assert out["metrics"]["r2"] == 0.9
    assert "val_obs" not in out["metrics"]  # always slim over MCP
    assert out["metrics"]["residuals"] == [0.1]


def test_tool_works_from_non_main_thread(mcp_app):
    """Regression guard for the thread-local pitfall: tool_boundary must push
    its own app context per call — FastMCP executes sync tools on worker
    threads where no context exists. (DB-free tool: the test sqlite is
    per-thread, but a context-less call would fail long before the DB.)"""
    from project.mcp_server.tools.refs import crest_get_model_registry

    result: list = []
    errors: list = []

    def call():
        try:
            result.extend(crest_get_model_registry())
        except Exception as exc:  # pragma: no cover - failure detail
            errors.append(exc)

    t = threading.Thread(target=call)
    t.start()
    t.join()

    assert not errors
    assert "LogisticRegression" in {m["algorithm"] for m in result}
