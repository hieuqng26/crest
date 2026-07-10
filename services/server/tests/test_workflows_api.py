"""
Tests for the /api/workflows blueprint: launching a multi-target
train -> forecast -> credit-analysis pipeline, dataset resolution, and
workflow-level cancel/delete lifecycle.

Run from services/server/:
    pytest tests/test_workflows_api.py -v
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


@pytest.fixture()
def mock_celery_task():
    with patch("project.services.workflows.run_calibration.delay"):
        yield


CAL_COLUMNS = [
    "sector",
    "subsector",
    "total_assets",
    "total_shortterm_debts",
    "total_longterm_debts",
    "inflation_rate",
    "gdp_growth",
    "local_cal_metric",
]
CAL_DTYPES = {
    "sector": "object",
    "subsector": "object",
    "total_assets": "float64",
    "total_shortterm_debts": "float64",
    "total_longterm_debts": "float64",
    "inflation_rate": "float64",
    "gdp_growth": "float64",
    "local_cal_metric": "float64",
}
FORECAST_COLUMNS = [
    "date",
    "scenario",
    "sector",
    "subsector",
    "inflation_rate",
    "gdp_growth",
]


def _schema(columns, dtypes=None):
    return json.dumps({"columns": columns, "dtypes": dtypes or {}})


@pytest.fixture()
def base_env(app, make_user):
    from project import db
    from project.db_models.calibration_models import Dataset, ModelConfig

    user = make_user("modeler@example.com", "sysadmin")
    now = datetime.now(timezone.utc)

    cal_ds = Dataset(
        name="cal-data",
        source="upload",
        file_path="uploads/test/cal.csv",
        schema_json=_schema(CAL_COLUMNS, CAL_DTYPES),
        row_count=500,
        created_by=user.email,
        status="ready",
        kind="calibration",
        created_at=now,
    )
    fc_ds = Dataset(
        name="forecast-data",
        source="upload",
        file_path="uploads/test/forecast.csv",
        schema_json=_schema(FORECAST_COLUMNS),
        row_count=200,
        created_by=user.email,
        status="ready",
        kind="forecast",
        created_at=now,
    )
    cfg = ModelConfig(
        name="elastic-default",
        family="regression",
        algorithm="ElasticNet",
        hyperparams_json=json.dumps({"alpha": 1.0, "l1_ratio": 0.5}),
        train_split=0.8,
        created_by=user.email,
    )
    db.session.add_all([cal_ds, fc_ds, cfg])
    db.session.commit()
    return {"user": user, "cal_ds": cal_ds, "fc_ds": fc_ds, "cfg": cfg}


class TestResolveDatasets:
    def test_picks_newest_dataset_per_kind(self, client, login, base_env):
        from project import db
        from project.db_models.calibration_models import Dataset

        d = base_env
        login(d["user"].email)

        older = Dataset(
            name="older-cal-data",
            source="upload",
            file_path="uploads/test/older.csv",
            schema_json=_schema(CAL_COLUMNS, CAL_DTYPES),
            row_count=10,
            created_by=d["user"].email,
            status="ready",
            kind="calibration",
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        db.session.add(older)
        db.session.commit()

        resp = client.get("/api/workflows/resolve-datasets")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["calibration"]["id"] == d["cal_ds"].id
        assert body["forecast"]["id"] == d["fc_ds"].id
        assert body["credit"] is None
        assert body["financial_portfolio"] is None


class TestCreateWorkflowValidation:
    def test_rejects_empty_targets(self, client, login, base_env, mock_celery_task):
        d = base_env
        login(d["user"].email)
        resp = client.post(
            "/api/workflows/",
            json={"name": "wf1", "model_config_id": d["cfg"].id, "targets": []},
        )
        assert resp.status_code == 400
        assert "targets" in resp.get_json()["error"]

    def test_rejects_duplicate_targets(self, client, login, base_env, mock_celery_task):
        d = base_env
        login(d["user"].email)
        resp = client.post(
            "/api/workflows/",
            json={
                "name": "wf1",
                "model_config_id": d["cfg"].id,
                "targets": [
                    {"target_col": "total_assets"},
                    {"target_col": "total_assets"},
                ],
            },
        )
        assert resp.status_code == 400
        assert "unique" in resp.get_json()["error"]

    def test_rejects_missing_calibration_dataset(self, client, login, app, make_user):
        from project import db
        from project.db_models.calibration_models import ModelConfig

        user = make_user("modeler2@example.com", "sysadmin")
        cfg = ModelConfig(
            name="cfg-only",
            family="regression",
            algorithm="ElasticNet",
            hyperparams_json="{}",
            train_split=0.8,
            created_by=user.email,
        )
        db.session.add(cfg)
        db.session.commit()

        login(user.email)
        with patch("project.services.workflows.run_calibration.delay"):
            resp = client.post(
                "/api/workflows/",
                json={
                    "name": "wf1",
                    "model_config_id": cfg.id,
                    "targets": [{"target_col": "total_assets"}],
                },
            )
        assert resp.status_code == 422
        assert "calibration dataset" in resp.get_json()["error"]

    def test_rejects_target_not_in_calibration_schema(
        self, client, login, base_env, mock_celery_task
    ):
        d = base_env
        login(d["user"].email)
        resp = client.post(
            "/api/workflows/",
            json={
                "name": "wf1",
                "model_config_id": d["cfg"].id,
                "targets": [{"target_col": "not_a_real_column"}],
            },
        )
        assert resp.status_code == 422
        assert "not_a_real_column" in resp.get_json()["error"]

    def test_rejects_feature_not_in_forecast_dataset(
        self, client, login, base_env, mock_celery_task
    ):
        d = base_env
        login(d["user"].email)
        resp = client.post(
            "/api/workflows/",
            json={
                "name": "wf1",
                "model_config_id": d["cfg"].id,
                "targets": [
                    {
                        "target_col": "total_assets",
                        "feature_cols": ["local_cal_metric"],
                    }
                ],
            },
        )
        assert resp.status_code == 422
        assert "local_cal_metric" in resp.get_json()["error"]

    def test_slot_incomplete_launch_still_succeeds(
        self, client, login, base_env, mock_celery_task
    ):
        d = base_env
        login(d["user"].email)
        resp = client.post(
            "/api/workflows/",
            json={
                "name": "wf-partial",
                "model_config_id": d["cfg"].id,
                "targets": [{"target_col": "total_assets"}],
            },
        )
        assert resp.status_code == 202, resp.get_json()
        body = resp.get_json()
        assert body["status"] == "queued"
        assert len(body["targets"]) == 1


class TestCreateWorkflowSuccess:
    def test_creates_one_calibration_run_per_target_with_workflow_run_id(
        self, client, login, base_env, mock_celery_task
    ):
        from project.db_models.calibration_models import CalibrationRun
        from project.db_models.workflow_models import WorkflowRun

        d = base_env
        cal_ds_id = d["cal_ds"].id
        fc_ds_id = d["fc_ds"].id
        cfg_id = d["cfg"].id
        login(d["user"].email)
        resp = client.post(
            "/api/workflows/",
            json={
                "name": "wf-full",
                "model_config_id": cfg_id,
                "targets": [
                    {"target_col": "total_assets"},
                    {"target_col": "total_shortterm_debts"},
                    {"target_col": "total_longterm_debts"},
                ],
            },
        )
        assert resp.status_code == 202, resp.get_json()
        body = resp.get_json()
        wf = WorkflowRun.query.filter_by(run_id=body["run_id"]).first()
        assert wf is not None
        assert wf.calibration_dataset_id == cal_ds_id
        assert wf.forecast_dataset_id == fc_ds_id

        cal_runs = CalibrationRun.query.filter_by(workflow_run_id=wf.id).all()
        assert len(cal_runs) == 3
        assert {c.target_col for c in cal_runs} == {
            "total_assets",
            "total_shortterm_debts",
            "total_longterm_debts",
        }
        for c in cal_runs:
            feats = json.loads(c.feature_cols_json)
            assert "local_cal_metric" not in feats  # not in forecast dataset
            assert set(feats) <= {"inflation_rate", "gdp_growth"}


@pytest.fixture()
def workflow_with_children(app, base_env):
    from project import db
    from project.db_models.calibration_models import CalibrationRun
    from project.db_models.workflow_models import WorkflowRun

    d = base_env
    wf = WorkflowRun(
        run_id="wf-children-1",
        name="wf-children",
        status="running",
        current_stage="training",
        triggered_by=d["user"].email,
        created_at=datetime.now(timezone.utc),
        calibration_dataset_id=d["cal_ds"].id,
        forecast_dataset_id=d["fc_ds"].id,
    )
    db.session.add(wf)
    db.session.commit()

    cal = CalibrationRun(
        run_id="wf-children-cal-1",
        dataset_id=d["cal_ds"].id,
        model_config_id=d["cfg"].id,
        status="running",
        triggered_by=d["user"].email,
        target_col="total_assets",
        workflow_run_id=wf.id,
    )
    db.session.add(cal)
    db.session.commit()
    return {**d, "wf": wf, "cal": cal}


class TestWorkflowChildGuards:
    def test_cannot_delete_calibration_child_directly(
        self, client, login, workflow_with_children
    ):
        d = workflow_with_children
        cal_run_id = d["cal"].run_id
        login(d["user"].email)
        # must cancel first since it's "running"
        with patch("project.workers.tasks.advance_workflow.delay"):
            client.post(f"/api/calibrations/{cal_run_id}/cancel")
        resp = client.delete(f"/api/calibrations/{cal_run_id}")
        assert resp.status_code == 409
        assert "workflow" in resp.get_json()["error"].lower()


class TestWorkflowCancel:
    def test_cancel_marks_children_and_workflow_failed(
        self, client, login, workflow_with_children
    ):
        d = workflow_with_children
        wf_run_id = d["wf"].run_id
        cal_run_id = d["cal"].run_id
        login(d["user"].email)
        resp = client.post(f"/api/workflows/{wf_run_id}/cancel")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "failed"

        from project.db_models.calibration_models import CalibrationRun

        cal = CalibrationRun.query.filter_by(run_id=cal_run_id).first()
        assert cal.status == "failed"
        assert cal.error_message == "Cancelled by user"


class TestWorkflowDelete:
    def test_delete_marks_deleting_and_dispatches_task(
        self, client, login, app, base_env
    ):
        """The route is async now: it flips the workflow to `deleting`, returns
        202, and dispatches the purge task (mocked here) — it does NOT delete
        inline."""
        from project import db
        from project.db_models.calibration_models import CalibrationRun
        from project.db_models.workflow_models import WorkflowRun

        d = base_env
        wf = WorkflowRun(
            run_id="wf-delete-1",
            name="wf-delete",
            status="success",
            current_stage="done",
            triggered_by=d["user"].email,
            created_at=datetime.now(timezone.utc),
            calibration_dataset_id=d["cal_ds"].id,
            forecast_dataset_id=d["fc_ds"].id,
        )
        db.session.add(wf)
        db.session.commit()
        cal = CalibrationRun(
            run_id="wf-delete-cal-1",
            dataset_id=d["cal_ds"].id,
            model_config_id=d["cfg"].id,
            status="success",
            triggered_by=d["user"].email,
            target_col="total_assets",
            workflow_run_id=wf.id,
        )
        db.session.add(cal)
        db.session.commit()

        login(d["user"].email)
        with patch(
            "project.api.workflows.routes.delete_workflow_task.delay"
        ) as mock_delay:
            resp = client.delete(f"/api/workflows/{wf.run_id}")
        assert resp.status_code == 202
        assert resp.get_json()["status"] == "deleting"
        mock_delay.assert_called_once_with("wf-delete-1")

        # Nothing deleted yet — only the status changed.
        row = WorkflowRun.query.filter_by(run_id="wf-delete-1").first()
        assert row is not None and row.status == "deleting"
        assert (
            CalibrationRun.query.filter_by(run_id="wf-delete-cal-1").first() is not None
        )

    def test_purge_workflow_removes_all_children_no_orphans(
        self, client, app, base_env
    ):
        """purge_workflow (run by the Celery task) set-deletes the workflow and
        every child run + result/log/segment row, leaving no orphans."""
        from project import db
        from project.core.workflow_delete import purge_workflow
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunLog,
            CalibrationRunSegment,
        )
        from project.db_models.forecast_models import (
            ForecastRun,
            ForecastRunResult,
        )
        from project.db_models.workflow_models import WorkflowRun

        d = base_env
        wf = WorkflowRun(
            run_id="wf-purge-1",
            name="wf-purge",
            status="deleting",
            current_stage="done",
            triggered_by=d["user"].email,
            created_at=datetime.now(timezone.utc),
            calibration_dataset_id=d["cal_ds"].id,
            forecast_dataset_id=d["fc_ds"].id,
        )
        db.session.add(wf)
        db.session.commit()
        cal = CalibrationRun(
            run_id="wf-purge-cal-1",
            dataset_id=d["cal_ds"].id,
            model_config_id=d["cfg"].id,
            status="success",
            triggered_by=d["user"].email,
            target_col="total_assets",
            workflow_run_id=wf.id,
        )
        db.session.add(cal)
        db.session.commit()
        db.session.add_all(
            [
                CalibrationRunLog(
                    run_id="wf-purge-cal-1",
                    logged_at=datetime.now(timezone.utc),
                    level="info",
                    message="hi",
                ),
                CalibrationRunSegment(
                    calibration_run_id=cal.id,
                    segment_key="banks__EU",
                    sector="banks",
                    split_by="country",
                    split_value="EU",
                    status="success",
                ),
            ]
        )
        fr = ForecastRun(
            run_id="wf-purge-fr-1",
            calibration_run_id=cal.id,
            dataset_id=d["fc_ds"].id,
            status="success",
            workflow_run_id=wf.id,
        )
        db.session.add(fr)
        db.session.commit()
        db.session.add(
            ForecastRunResult(forecast_run_id=fr.id, date="2026", predicted=1.0)
        )
        db.session.commit()

        # Snapshot the PKs before purge_workflow — it closes the session, which
        # expires these ORM instances (accessing cal.id/fr.id afterwards would
        # raise DetachedInstanceError).
        wf_id = wf.id
        cal_id = cal.id
        fr_id = fr.id
        # MinIO cleanup is best-effort I/O — stub it out in the unit test.
        with patch("project.core.workflow_delete.storage.remove_prefix") as mock_rm:
            purge_workflow(wf_id)
        mock_rm.assert_called_once_with("artifacts/wf-purge-cal-1/")

        assert WorkflowRun.query.filter_by(id=wf_id).first() is None
        assert CalibrationRun.query.filter_by(run_id="wf-purge-cal-1").first() is None
        assert ForecastRun.query.filter_by(run_id="wf-purge-fr-1").first() is None
        assert CalibrationRunLog.query.filter_by(run_id="wf-purge-cal-1").count() == 0
        assert (
            CalibrationRunSegment.query.filter_by(calibration_run_id=cal_id).count()
            == 0
        )
        assert ForecastRunResult.query.filter_by(forecast_run_id=fr_id).count() == 0

    def test_delete_blocked_while_child_active(
        self, client, login, workflow_with_children
    ):
        d = workflow_with_children
        login(d["user"].email)
        resp = client.delete(f"/api/workflows/{d['wf'].run_id}")
        assert resp.status_code == 409
