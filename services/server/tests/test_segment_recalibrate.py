"""
Tests for POST /calibrations/<run_id>/segments/<segment_key>/recalibrate —
re-running a single segment of a completed segmented run with an optional
hyperparameter override.

Run from services/server/:
    pytest tests/test_segment_recalibrate.py -v
"""

import json
from unittest.mock import patch

import pytest


@pytest.fixture()
def mock_segment_task():
    with patch("project.api.calibrations.routes.run_segment_calibration.delay") as m:
        yield m


@pytest.fixture()
def segmented_run(app, make_user):
    from project import db
    from project.db_models.calibration_models import (
        CalibrationRun,
        CalibrationRunSegment,
        Dataset,
        ModelConfig,
    )

    user = make_user("modeler@example.com", "sysadmin")
    ds = Dataset(
        name="test-calibration-data",
        source="upload",
        file_path="uploads/test/data.csv",
        row_count=100,
        created_by=user.email,
        status="ready",
        kind="calibration",
    )
    cfg = ModelConfig(
        name="elastic-default",
        family="regression",
        algorithm="ElasticNet",
        hyperparams_json=json.dumps({"alpha": 1.0, "l1_ratio": 0.5}),
        train_split=0.8,
        created_by=user.email,
    )
    db.session.add_all([ds, cfg])
    db.session.commit()

    run = CalibrationRun(
        run_id="seg-run-1",
        dataset_id=ds.id,
        model_config_id=cfg.id,
        status="success",
        triggered_by=user.email,
        target_col="total_assets",
        feature_cols_json=json.dumps(["inflation_rate"]),
        seg_sectors_json=json.dumps(["Financials"]),
        seg_split_by="subsector",
        seg_max_segments=5,
    )
    db.session.add(run)
    db.session.commit()

    seg = CalibrationRunSegment(
        calibration_run_id=run.id,
        segment_key="Financials__Banks",
        sector="Financials",
        split_by="subsector",
        split_value="Banks",
        model_config_id=cfg.id,
        row_count=42,
        status="success",
        train_metrics_json=json.dumps({"r2": 0.7}),
        val_metrics_json=json.dumps({"r2": 0.65}),
    )
    db.session.add(seg)
    db.session.commit()

    return {"user": user, "run": run, "segment": seg, "cfg": cfg}


class TestRecalibrateSegment:
    def _url(self, run_id, segment_key):
        return f"/api/calibrations/{run_id}/segments/{segment_key}/recalibrate"

    def test_queues_segment_and_persists_hyperparams_override(
        self, client, login, segmented_run, mock_segment_task
    ):
        d = segmented_run
        login(d["user"].email)
        resp = client.post(
            self._url("seg-run-1", "Financials__Banks"),
            json={"hyperparams": {"alpha": 0.3, "l1_ratio": 0.2}},
        )
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["status"] == "queued"
        assert body["hyperparams"] == {"alpha": 0.3, "l1_ratio": 0.2}
        assert body["algorithm"] == "ElasticNet"
        mock_segment_task.assert_called_once_with("seg-run-1", "Financials__Banks")

        from project.db_models.calibration_models import CalibrationRunSegment

        refreshed = CalibrationRunSegment.query.filter_by(
            segment_key="Financials__Banks"
        ).first()
        assert refreshed.status == "queued"
        assert json.loads(refreshed.hyperparams_json) == {
            "alpha": 0.3,
            "l1_ratio": 0.2,
        }

    def test_without_hyperparams_reruns_with_existing_config(
        self, client, login, segmented_run, mock_segment_task
    ):
        d = segmented_run
        login(d["user"].email)
        resp = client.post(self._url("seg-run-1", "Financials__Banks"), json={})
        assert resp.status_code == 202
        assert resp.get_json()["hyperparams"] is None

    def test_persists_model_config_and_feature_overrides(
        self, client, login, segmented_run, mock_segment_task
    ):
        from project import db
        from project.db_models.calibration_models import (
            CalibrationRunSegment,
            ModelConfig,
        )

        d = segmented_run
        # A second saved config to switch the segment to.
        other = ModelConfig(
            name="ridge-alt",
            family="regression",
            algorithm="Ridge",
            hyperparams_json=json.dumps({"alpha": 2.0}),
            train_split=0.8,
            created_by=d["user"].email,
        )
        db.session.add(other)
        db.session.commit()
        other_id = other.id

        login(d["user"].email)
        resp = client.post(
            self._url("seg-run-1", "Financials__Banks"),
            json={"model_config_id": other_id, "feature_cols": ["inflation_rate"]},
        )
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["model_config_id"] == other_id
        assert body["feature_cols"] == ["inflation_rate"]
        assert body["algorithm"] == "Ridge"

        refreshed = CalibrationRunSegment.query.filter_by(
            segment_key="Financials__Banks"
        ).first()
        assert refreshed.model_config_id == other_id
        assert json.loads(refreshed.feature_cols_json) == ["inflation_rate"]

    def test_400_when_model_config_missing(
        self, client, login, segmented_run, mock_segment_task
    ):
        login(segmented_run["user"].email)
        resp = client.post(
            self._url("seg-run-1", "Financials__Banks"),
            json={"model_config_id": 999999},
        )
        assert resp.status_code == 400

    def test_400_when_feature_cols_not_list(
        self, client, login, segmented_run, mock_segment_task
    ):
        login(segmented_run["user"].email)
        resp = client.post(
            self._url("seg-run-1", "Financials__Banks"),
            json={"feature_cols": "inflation_rate"},
        )
        assert resp.status_code == 400

    def test_404_when_run_missing(
        self, client, login, segmented_run, mock_segment_task
    ):
        login(segmented_run["user"].email)
        resp = client.post(self._url("does-not-exist", "Financials__Banks"))
        assert resp.status_code == 404

    def test_404_when_segment_missing(
        self, client, login, segmented_run, mock_segment_task
    ):
        login(segmented_run["user"].email)
        resp = client.post(self._url("seg-run-1", "Energy__Norway"))
        assert resp.status_code == 404

    def test_409_when_run_not_success(
        self, client, login, segmented_run, mock_segment_task
    ):
        from project import db

        d = segmented_run
        d["run"].status = "running"
        db.session.commit()
        login(d["user"].email)
        resp = client.post(self._url("seg-run-1", "Financials__Banks"))
        assert resp.status_code == 409

    def test_409_when_segment_already_retraining(
        self, client, login, segmented_run, mock_segment_task
    ):
        from project import db

        d = segmented_run
        d["segment"].status = "running"
        db.session.commit()
        login(d["user"].email)
        resp = client.post(self._url("seg-run-1", "Financials__Banks"))
        assert resp.status_code == 409

    def test_400_when_hyperparams_not_object(
        self, client, login, segmented_run, mock_segment_task
    ):
        login(segmented_run["user"].email)
        resp = client.post(
            self._url("seg-run-1", "Financials__Banks"),
            json={"hyperparams": "not-an-object"},
        )
        assert resp.status_code == 400
