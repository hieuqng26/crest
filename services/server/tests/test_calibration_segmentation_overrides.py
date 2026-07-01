"""
Tests for per-sector segmentation overrides (seg_sector_overrides_json on
CalibrationRun, model_config_id on CalibrationRunSegment).

Run from services/server/:
    pytest tests/test_calibration_segmentation_overrides.py -v
"""

import json
from unittest.mock import patch

import pytest


@pytest.fixture()
def mock_celery_task():
    """Mock the Celery task to avoid Redis dependency in tests."""
    with patch("project.api.calibrations.routes.run_calibration.delay"):
        yield


@pytest.fixture()
def dataset_and_configs(app, make_user):
    from project import db
    from project.db_models.calibration_models import Dataset, ModelConfig

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
    cfg_a = ModelConfig(
        name="elastic-default",
        family="regression",
        algorithm="ElasticNet",
        hyperparams_json=json.dumps({"alpha": 1.0, "l1_ratio": 0.5}),
        train_split=0.8,
        created_by=user.email,
    )
    cfg_b = ModelConfig(
        name="rf-tuned",
        family="regression",
        algorithm="RandomForest",
        hyperparams_json=json.dumps({"n_estimators": 200}),
        train_split=0.8,
        created_by=user.email,
    )
    db.session.add_all([ds, cfg_a, cfg_b])
    db.session.commit()
    return {"user": user, "dataset": ds, "cfg_a": cfg_a, "cfg_b": cfg_b}


class TestCalibrationRunSectorOverridesModel:
    def test_seg_sector_overrides_json_round_trips_through_to_dict(
        self, app, dataset_and_configs
    ):
        from project import db
        from project.db_models.calibration_models import CalibrationRun

        d = dataset_and_configs
        overrides = {
            "Financials": {
                "split_by": "country",
                "max_segments": 8,
                "model_config_id": d["cfg_b"].id,
            },
            "Energy": {"feature_cols": ["oil_price", "notional_gdp"]},
        }
        run = CalibrationRun(
            run_id="test-run-1",
            dataset_id=d["dataset"].id,
            model_config_id=d["cfg_a"].id,
            status="queued",
            triggered_by=d["user"].email,
            target_col="total_assets",
            feature_cols_json=json.dumps(["inflation_rate", "notional_gdp"]),
            seg_sectors_json=json.dumps(["Financials", "Energy"]),
            seg_split_by="subsector",
            seg_max_segments=5,
            seg_sector_overrides_json=json.dumps(overrides),
        )
        db.session.add(run)
        db.session.commit()

        fetched = CalibrationRun.query.filter_by(run_id="test-run-1").first()
        result = fetched.to_dict()
        assert result["seg_sector_overrides"] == overrides

    def test_seg_sector_overrides_defaults_to_none(self, app, dataset_and_configs):
        from project import db
        from project.db_models.calibration_models import CalibrationRun

        d = dataset_and_configs
        run = CalibrationRun(
            run_id="test-run-2",
            dataset_id=d["dataset"].id,
            model_config_id=d["cfg_a"].id,
            status="queued",
            triggered_by=d["user"].email,
        )
        db.session.add(run)
        db.session.commit()

        fetched = CalibrationRun.query.filter_by(run_id="test-run-2").first()
        assert fetched.to_dict()["seg_sector_overrides"] is None


class TestCalibrationRunSegmentModelConfigId:
    def test_model_config_id_persists_and_serializes(self, app, dataset_and_configs):
        from project import db
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunSegment,
        )

        d = dataset_and_configs
        run = CalibrationRun(
            run_id="test-run-3",
            dataset_id=d["dataset"].id,
            model_config_id=d["cfg_a"].id,
            status="success",
            triggered_by=d["user"].email,
        )
        db.session.add(run)
        db.session.commit()

        seg = CalibrationRunSegment(
            calibration_run_id=run.id,
            segment_key="Financials__Retail Banking",
            sector="Financials",
            split_by="subsector",
            split_value="Retail Banking",
            status="success",
            model_config_id=d["cfg_b"].id,
        )
        db.session.add(seg)
        db.session.commit()

        fetched = CalibrationRunSegment.query.filter_by(
            segment_key="Financials__Retail Banking"
        ).first()
        assert fetched.to_dict()["model_config_id"] == d["cfg_b"].id

    def test_model_config_id_nullable(self, app, dataset_and_configs):
        from project import db
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunSegment,
        )

        d = dataset_and_configs
        run = CalibrationRun(
            run_id="test-run-4",
            dataset_id=d["dataset"].id,
            model_config_id=d["cfg_a"].id,
            status="success",
            triggered_by=d["user"].email,
        )
        db.session.add(run)
        db.session.commit()

        seg = CalibrationRunSegment(
            calibration_run_id=run.id,
            segment_key="Energy__Oil & Gas",
            sector="Energy",
            split_by="subsector",
            split_value="Oil & Gas",
            status="success",
        )
        db.session.add(seg)
        db.session.commit()

        fetched = CalibrationRunSegment.query.filter_by(
            segment_key="Energy__Oil & Gas"
        ).first()
        assert fetched.to_dict()["model_config_id"] is None


class TestCreateRunSectorOverridesAPI:
    def test_rejects_override_for_sector_not_in_sectors_list(
        self, client, login, dataset_and_configs, mock_celery_task
    ):
        d = dataset_and_configs
        login(d["user"].email)
        resp = client.post(
            "/api/calibrations/",
            json={
                "dataset_id": d["dataset"].id,
                "model_config_id": d["cfg_a"].id,
                "target_col": "total_assets",
                "segmentation": {
                    "sectors": ["Financials"],
                    "split_by": "subsector",
                    "max_segments": 5,
                    "sector_overrides": {"Energy": {"max_segments": 8}},
                },
            },
        )
        assert resp.status_code == 400
        assert "Energy" in resp.get_json()["error"]

    def test_rejects_invalid_split_by_in_override(
        self, client, login, dataset_and_configs, mock_celery_task
    ):
        d = dataset_and_configs
        login(d["user"].email)
        resp = client.post(
            "/api/calibrations/",
            json={
                "dataset_id": d["dataset"].id,
                "model_config_id": d["cfg_a"].id,
                "target_col": "total_assets",
                "segmentation": {
                    "sectors": ["Financials"],
                    "split_by": "subsector",
                    "max_segments": 5,
                    "sector_overrides": {"Financials": {"split_by": "region"}},
                },
            },
        )
        assert resp.status_code == 400

    def test_rejects_unknown_model_config_id_in_override(
        self, client, login, dataset_and_configs, mock_celery_task
    ):
        d = dataset_and_configs
        login(d["user"].email)
        resp = client.post(
            "/api/calibrations/",
            json={
                "dataset_id": d["dataset"].id,
                "model_config_id": d["cfg_a"].id,
                "target_col": "total_assets",
                "segmentation": {
                    "sectors": ["Financials"],
                    "split_by": "subsector",
                    "max_segments": 5,
                    "sector_overrides": {"Financials": {"model_config_id": 999999}},
                },
            },
        )
        assert resp.status_code == 400

    def test_rejects_none_model_config_id_in_override(
        self, client, login, dataset_and_configs, mock_celery_task
    ):
        d = dataset_and_configs
        login(d["user"].email)
        resp = client.post(
            "/api/calibrations/",
            json={
                "dataset_id": d["dataset"].id,
                "model_config_id": d["cfg_a"].id,
                "target_col": "total_assets",
                "segmentation": {
                    "sectors": ["Financials"],
                    "split_by": "subsector",
                    "max_segments": 5,
                    "sector_overrides": {"Financials": {"model_config_id": None}},
                },
            },
        )
        assert resp.status_code == 400
        error_msg = resp.get_json()["error"]
        assert "model_config_id" in error_msg
        assert "must be an integer" in error_msg

    def test_accepts_valid_sector_overrides_and_stores_them(
        self, client, login, dataset_and_configs, mock_celery_task
    ):
        d = dataset_and_configs
        cfg_b_id = d["cfg_b"].id  # Capture ID before session is detached
        login(d["user"].email)
        resp = client.post(
            "/api/calibrations/",
            json={
                "dataset_id": d["dataset"].id,
                "model_config_id": d["cfg_a"].id,
                "target_col": "total_assets",
                "segmentation": {
                    "sectors": ["Financials", "Energy"],
                    "split_by": "subsector",
                    "max_segments": 5,
                    "sector_overrides": {
                        "Financials": {
                            "split_by": "country",
                            "max_segments": 8,
                            "model_config_id": cfg_b_id,
                        }
                    },
                },
            },
        )
        assert resp.status_code == 202, resp.get_json()
        body = resp.get_json()
        assert body["seg_sector_overrides"] == {
            "Financials": {
                "split_by": "country",
                "max_segments": 8,
                "model_config_id": cfg_b_id,
            }
        }
