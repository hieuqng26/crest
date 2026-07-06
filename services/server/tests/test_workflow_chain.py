"""
Tests for advance_workflow_impl — the DB-driven completion-check that chains
a workflow's training -> forecast -> credit-analysis stages.

Run from services/server/:
    pytest tests/test_workflow_chain.py -v

Note: advance_workflow_impl uses app_session(), which closes the SQLAlchemy
session on exit and detaches any previously-loaded ORM objects. Every test
here captures the plain int/str ids it needs *before* calling
advance_workflow_impl, and re-queries fresh rows afterward instead of
reusing stale object references.
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture()
def env(app, make_user):
    from project import db
    from project.db_models.calibration_models import Dataset, ModelConfig

    user = make_user("modeler@example.com", "sysadmin")
    cal_ds = Dataset(
        name="cal-data",
        source="upload",
        file_path="uploads/test/cal.csv",
        row_count=100,
        created_by=user.email,
        status="ready",
        kind="calibration",
    )
    fc_ds = Dataset(
        name="forecast-data",
        source="upload",
        file_path="uploads/test/forecast.csv",
        row_count=50,
        created_by=user.email,
        status="ready",
        kind="forecast",
    )
    credit_ds = Dataset(
        name="credit-data",
        source="upload",
        file_path="uploads/test/credit.csv",
        row_count=20,
        created_by=user.email,
        status="ready",
        kind="credit",
    )
    cfg = ModelConfig(
        name="elastic-default",
        family="regression",
        algorithm="ElasticNet",
        hyperparams_json=json.dumps({"alpha": 1.0}),
        train_split=0.8,
        created_by=user.email,
    )
    db.session.add_all([cal_ds, fc_ds, credit_ds, cfg])
    db.session.commit()
    return {
        "user_email": user.email,
        "cal_ds_id": cal_ds.id,
        "fc_ds_id": fc_ds.id,
        "credit_ds_id": credit_ds.id,
        "cfg_id": cfg.id,
    }


def _make_workflow(env, targets, credit=True) -> int:
    """Create a WorkflowRun + one queued CalibrationRun per target. Returns the
    workflow's int id (safe to use across advance_workflow_impl calls)."""
    from project import db
    from project.db_models.calibration_models import CalibrationRun
    from project.db_models.workflow_models import WorkflowRun

    wf = WorkflowRun(
        run_id=f"wf-{'-'.join(targets)}-{credit}",
        name="test-wf",
        status="queued",
        current_stage="training",
        triggered_by=env["user_email"],
        created_at=datetime.now(timezone.utc),
        calibration_dataset_id=env["cal_ds_id"],
        forecast_dataset_id=env["fc_ds_id"],
        credit_dataset_id=env["credit_ds_id"] if credit else None,
    )
    db.session.add(wf)
    db.session.commit()
    wf_id = wf.id

    for t in targets:
        c = CalibrationRun(
            run_id=f"cal-{t}-{wf_id}",
            dataset_id=env["cal_ds_id"],
            model_config_id=env["cfg_id"],
            status="queued",
            triggered_by=env["user_email"],
            target_col=t,
            feature_cols_json="[]",
            workflow_run_id=wf_id,
        )
        db.session.add(c)
    db.session.commit()
    return wf_id


def _set_cal_statuses(wf_id: int, statuses: dict):
    from project import db
    from project.db_models.calibration_models import CalibrationRun

    for cal in CalibrationRun.query.filter_by(workflow_run_id=wf_id).all():
        if cal.target_col in statuses:
            cal.status = statuses[cal.target_col]
            if statuses[cal.target_col] == "failed":
                cal.error_message = "boom"
    db.session.commit()


def _succeed_all_cals(wf_id: int):
    from project import db
    from project.db_models.calibration_models import CalibrationRun

    for cal in CalibrationRun.query.filter_by(workflow_run_id=wf_id).all():
        cal.status = "success"
    db.session.commit()


def _succeed_all_forecasts(wf_id: int):
    from project import db
    from project.db_models.forecast_models import ForecastRun

    for fr in ForecastRun.query.filter_by(workflow_run_id=wf_id).all():
        fr.status = "success"
    db.session.commit()


class TestTrainingToForecast:
    def test_creates_one_forecast_run_per_target_exactly_once(self, app, env):
        from project.db_models.forecast_models import ForecastRun
        from project.workers.tasks import advance_workflow_impl

        wf_id = _make_workflow(env, ["total_assets", "total_shortterm_debts"])
        _succeed_all_cals(wf_id)

        with patch("project.workers.tasks.run_forecast.delay") as mock_fc:
            advance_workflow_impl(wf_id)
            advance_workflow_impl(wf_id)  # second concurrent-ish call

        fcs = ForecastRun.query.filter_by(workflow_run_id=wf_id).all()
        assert len(fcs) == 2  # not 4 — stage guard prevented duplicate creation
        assert mock_fc.call_count == 2


class TestFailurePropagation:
    def test_failed_calibration_fails_workflow_with_message_no_forecasts(
        self, app, env
    ):
        from project.db_models.forecast_models import ForecastRun
        from project.db_models.workflow_models import WorkflowRun
        from project.workers.tasks import advance_workflow_impl

        wf_id = _make_workflow(env, ["total_assets", "total_shortterm_debts"])
        _set_cal_statuses(
            wf_id, {"total_assets": "success", "total_shortterm_debts": "failed"}
        )

        with patch("project.workers.tasks.run_forecast.delay"):
            advance_workflow_impl(wf_id)

        refreshed = WorkflowRun.query.get(wf_id)
        assert refreshed.status == "failed"
        assert "total_shortterm_debts" in refreshed.error_message
        assert "boom" in refreshed.error_message
        assert ForecastRun.query.filter_by(workflow_run_id=wf_id).count() == 0


class TestForecastToAnalysis:
    def test_slot_complete_creates_credit_run_with_correct_slots(self, app, env):
        from project.db_models.calibration_models import CalibrationRun
        from project.db_models.credit_models import (
            CreditRiskForecastInput,
            CreditRiskRun,
        )
        from project.db_models.forecast_models import ForecastRun
        from project.workers.tasks import advance_workflow_impl

        wf_id = _make_workflow(
            env, ["total_assets", "total_shortterm_debts", "total_longterm_debts"]
        )
        _succeed_all_cals(wf_id)

        with patch("project.workers.tasks.run_forecast.delay"):
            advance_workflow_impl(wf_id)  # creates forecast runs, stage -> forecast

        fcs = ForecastRun.query.filter_by(workflow_run_id=wf_id).all()
        assert len(fcs) == 3
        _succeed_all_forecasts(wf_id)

        with patch("project.workers.tasks.run_credit_analysis.delay") as mock_cr:
            advance_workflow_impl(wf_id)  # should create + dispatch credit run

        cr = CreditRiskRun.query.filter_by(workflow_run_id=wf_id).first()
        assert cr is not None
        assert mock_cr.call_count == 1

        inputs = CreditRiskForecastInput.query.filter_by(credit_risk_run_id=cr.id).all()
        slot_by_target = {
            "total_assets": "total_assets",
            "total_shortterm_debts": "short_term_debts",
            "total_longterm_debts": "long_term_debts",
        }
        cals = CalibrationRun.query.filter_by(workflow_run_id=wf_id).all()
        target_by_cal_id = {c.id: c.target_col for c in cals}
        fcs_refreshed = ForecastRun.query.filter_by(workflow_run_id=wf_id).all()
        fr_by_id = {fr.id: fr for fr in fcs_refreshed}
        assert len(inputs) == 3
        for inp in inputs:
            fr = fr_by_id[inp.forecast_run_id]
            expected_slot = slot_by_target[target_by_cal_id[fr.calibration_run_id]]
            assert inp.slot == expected_slot

    def test_slot_incomplete_marks_success_with_skip_reason(self, app, env):
        from project.db_models.credit_models import CreditRiskRun
        from project.db_models.forecast_models import ForecastRun
        from project.db_models.workflow_models import WorkflowRun
        from project.workers.tasks import advance_workflow_impl

        wf_id = _make_workflow(env, ["total_assets"])  # missing 2 of 3 slots
        _succeed_all_cals(wf_id)

        with patch("project.workers.tasks.run_forecast.delay"):
            advance_workflow_impl(wf_id)

        _succeed_all_forecasts(wf_id)

        with patch("project.workers.tasks.run_credit_analysis.delay") as mock_cr:
            advance_workflow_impl(wf_id)

        refreshed = WorkflowRun.query.get(wf_id)
        assert refreshed.status == "success"
        assert refreshed.current_stage == "done"
        assert refreshed.analysis_skipped_reason is not None
        assert "total_shortterm_debts" in refreshed.analysis_skipped_reason
        assert "total_longterm_debts" in refreshed.analysis_skipped_reason
        assert CreditRiskRun.query.filter_by(workflow_run_id=wf_id).count() == 0
        mock_cr.assert_not_called()
        assert ForecastRun.query.filter_by(workflow_run_id=wf_id).count() == 1

    def test_no_credit_dataset_skips_with_reason(self, app, env):
        from project.db_models.workflow_models import WorkflowRun
        from project.workers.tasks import advance_workflow_impl

        wf_id = _make_workflow(
            env,
            ["total_assets", "total_shortterm_debts", "total_longterm_debts"],
            credit=False,
        )
        _succeed_all_cals(wf_id)

        with patch("project.workers.tasks.run_forecast.delay"):
            advance_workflow_impl(wf_id)

        _succeed_all_forecasts(wf_id)

        with patch("project.workers.tasks.run_credit_analysis.delay"):
            advance_workflow_impl(wf_id)

        refreshed = WorkflowRun.query.get(wf_id)
        assert refreshed.status == "success"
        assert refreshed.analysis_skipped_reason is not None


class TestAnalysisToDone:
    def test_analysis_success_finalizes_workflow(self, app, env):
        from project import db
        from project.db_models.credit_models import CreditRiskRun
        from project.db_models.workflow_models import WorkflowRun
        from project.workers.tasks import advance_workflow_impl

        wf_id = _make_workflow(
            env, ["total_assets", "total_shortterm_debts", "total_longterm_debts"]
        )
        _succeed_all_cals(wf_id)

        with patch("project.workers.tasks.run_forecast.delay"):
            advance_workflow_impl(wf_id)

        _succeed_all_forecasts(wf_id)

        with patch("project.workers.tasks.run_credit_analysis.delay"):
            advance_workflow_impl(wf_id)

        cr = CreditRiskRun.query.filter_by(workflow_run_id=wf_id).first()
        cr.status = "success"
        db.session.commit()

        advance_workflow_impl(wf_id)

        refreshed = WorkflowRun.query.get(wf_id)
        assert refreshed.status == "success"
        assert refreshed.current_stage == "done"
