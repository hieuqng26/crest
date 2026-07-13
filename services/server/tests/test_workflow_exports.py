"""Tests for the async workflow export feature (Download tab):
listing outputs, building each output's file bytes, creating/deduping jobs,
running the export worker, streaming the download, and expiry purge.

Run from services/server/:
    pytest tests/test_workflow_exports.py -v
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


def _schema(cols):
    return json.dumps({"columns": cols, "dtypes": {}})


@pytest.fixture()
def wf_env(app, make_user):
    """A completed workflow with data behind all three exportable outputs."""
    from project import db
    from project.db_models.calibration_models import (
        CalibrationRun,
        Dataset,
        Forecast,
        ForecastResult,
        ModelConfig,
    )
    from project.db_models.credit_models import CreditRiskResult, CreditRiskRun
    from project.db_models.forecast_models import ForecastRun, ForecastRunResult
    from project.db_models.workflow_models import WorkflowRun

    user = make_user("exporter@example.com", "sysadmin")
    now = datetime.now(timezone.utc)

    cal_ds = Dataset(
        name="cal",
        source="upload",
        file_path="uploads/t/cal.csv",
        schema_json=_schema(["total_assets"]),
        row_count=10,
        created_by=user.email,
        status="ready",
        kind="calibration",
        created_at=now,
    )
    fc_ds = Dataset(
        name="fc",
        source="upload",
        file_path="uploads/t/fc.csv",
        schema_json=_schema(["date"]),
        row_count=10,
        created_by=user.email,
        status="ready",
        kind="forecast",
        created_at=now,
    )
    cfg = ModelConfig(
        name="en",
        family="regression",
        algorithm="ElasticNet",
        hyperparams_json="{}",
        train_split=0.8,
        created_by=user.email,
    )
    db.session.add_all([cal_ds, fc_ds, cfg])
    db.session.commit()

    wf = WorkflowRun(
        run_id="wf-exp-1",
        name="Export WF",
        status="success",
        current_stage="done",
        triggered_by=user.email,
        created_at=now,
        calibration_dataset_id=cal_ds.id,
        forecast_dataset_id=fc_ds.id,
    )
    db.session.add(wf)
    db.session.commit()

    cal = CalibrationRun(
        run_id="wf-exp-cal-1",
        dataset_id=cal_ds.id,
        model_config_id=cfg.id,
        status="success",
        triggered_by=user.email,
        target_col="total_assets",
        workflow_run_id=wf.id,
    )
    db.session.add(cal)
    db.session.commit()

    # model_predictions source: Forecast + ForecastResult (actual vs predicted)
    fcast = Forecast(calibration_run_id=cal.id, created_at=now)
    db.session.add(fcast)
    db.session.commit()
    db.session.add_all(
        [
            ForecastResult(
                forecast_id=fcast.id,
                actual=1.0,
                predicted=1.1,
                client_id="c1",
                date="2025",
            ),
            ForecastResult(
                forecast_id=fcast.id,
                actual=2.0,
                predicted=1.8,
                client_id="c2",
                date="2025",
            ),
        ]
    )

    # forecast_results source: ForecastRun + ForecastRunResult
    fr = ForecastRun(
        run_id="wf-exp-fr-1",
        calibration_run_id=cal.id,
        dataset_id=fc_ds.id,
        status="success",
        workflow_run_id=wf.id,
    )
    db.session.add(fr)
    db.session.commit()
    db.session.add_all(
        [
            ForecastRunResult(
                forecast_run_id=fr.id,
                date="2026",
                predicted=3.0,
                sector="banks",
                scenario="Baseline",
            ),
            ForecastRunResult(
                forecast_run_id=fr.id,
                date="2027",
                predicted=3.2,
                sector="banks",
                scenario="Baseline",
            ),
        ]
    )

    # credit_results source: CreditRiskRun + CreditRiskResult (kmv/ecl json)
    cr = CreditRiskRun(
        run_id="wf-exp-cr-1",
        dataset_id=fc_ds.id,
        is_active=True,
        exposure=1.0,
        status="success",
        workflow_run_id=wf.id,
    )
    db.session.add(cr)
    db.session.commit()
    kmv = [
        {
            "YEAR": 2026,
            "SCENARIO": "Baseline",
            "PD": 0.02,
            "LGD": 0.45,
            "Rating": "Baa",
        },
        {
            "YEAR": 2027,
            "SCENARIO": "Baseline",
            "PD": 0.03,
            "LGD": 0.45,
            "Rating": "Baa",
        },
    ]
    ecl = [
        {"YEAR": 2026, "SCENARIO": "Baseline", "ECL_12M": 10.0, "ECL_Lifetime": 25.0}
    ]
    db.session.add(
        CreditRiskResult(
            run_id=cr.run_id,
            client_id="c1",
            kmv_json=json.dumps(kmv),
            ecl_json=json.dumps(ecl),
            sector="banks",
        )
    )
    db.session.commit()
    return {"user": user, "wf": wf}


class TestListOutputs:
    def test_lists_three_available_outputs(self, client, login, wf_env):
        login(wf_env["user"].email)
        r = client.get("/api/workflows/wf-exp-1/exports/outputs")
        assert r.status_code == 200
        outs = {o["key"]: o for o in r.get_json()["outputs"]}
        assert set(outs) == {"model_predictions", "forecast_results", "credit_results"}
        assert all(o["available"] for o in outs.values())


class TestBuildExportBytes:
    def test_builds_every_output_csv(self, app, wf_env):
        from project.services import workflow_exports as we

        for key in ("model_predictions", "forecast_results", "credit_results"):
            data, filename, mimetype, rows = we.build_export_bytes(
                "wf-exp-1", key, "csv"
            )
            assert rows > 0
            assert data  # non-empty csv bytes
            assert filename.endswith(".csv")
            assert mimetype == "text/csv"

    def test_builds_xlsx(self, app, wf_env):
        from project.services import workflow_exports as we

        data, filename, mimetype, rows = we.build_export_bytes(
            "wf-exp-1", "forecast_results", "xlsx"
        )
        assert filename.endswith(".xlsx")
        assert data[:2] == b"PK"  # xlsx is a zip container

    def test_credit_detail_shape(self, app, wf_env):
        from project.services import workflow_exports as we

        df = we._credit_full_detail_df(we._get_workflow("wf-exp-1"))
        assert len(df) == 2  # one row per KMV year × scenario
        assert {"client_id", "SCENARIO", "YEAR", "PD", "ECL_Lifetime"} <= set(
            df.columns
        )
        # ECL merged onto the matching year only
        row2026 = df[df["YEAR"] == 2026].iloc[0]
        assert row2026["ECL_Lifetime"] == 25.0


class TestCreateExport:
    def test_dispatches_to_exports_queue(self, client, login, wf_env):
        login(wf_env["user"].email)
        with patch("project.api.workflows.routes.export_dataset_task.apply_async") as m:
            r = client.post(
                "/api/workflows/wf-exp-1/exports",
                json={"output": "forecast_results", "format": "csv"},
            )
        assert r.status_code == 202
        job = r.get_json()
        assert job["status"] == "queued"
        m.assert_called_once()
        assert m.call_args.kwargs.get("queue") == "exports"

    def test_dedupes_active_job(self, client, login, wf_env):
        login(wf_env["user"].email)
        with patch("project.api.workflows.routes.export_dataset_task.apply_async"):
            a = client.post(
                "/api/workflows/wf-exp-1/exports",
                json={"output": "forecast_results", "format": "csv"},
            ).get_json()
            b = client.post(
                "/api/workflows/wf-exp-1/exports",
                json={"output": "forecast_results", "format": "csv"},
            ).get_json()
        assert a["job_id"] == b["job_id"]

    def test_unknown_output_rejected(self, client, login, wf_env):
        login(wf_env["user"].email)
        r = client.post(
            "/api/workflows/wf-exp-1/exports",
            json={"output": "nope", "format": "csv"},
        )
        assert r.status_code == 400


class TestWorkerAndDownload:
    def test_task_success_then_download(self, client, login, app, wf_env):
        from project.workers.tasks import export_dataset

        login(wf_env["user"].email)
        with patch("project.api.workflows.routes.export_dataset_task.apply_async"):
            job = client.post(
                "/api/workflows/wf-exp-1/exports",
                json={"output": "forecast_results", "format": "csv"},
            ).get_json()
        job_id = job["job_id"]

        captured = {}

        def fake_upload(name, data, content_type="application/octet-stream"):
            captured["name"] = name
            captured["data"] = data
            return f"mst-artifacts/{name}"

        with (
            patch("project.workers.export._make_flask_app", return_value=app),
            patch(
                "project.workers.export.storage.upload_bytes", side_effect=fake_upload
            ),
        ):
            export_dataset.apply(args=[job_id])

        # Job flipped to success with the object path recorded.
        body = client.get(f"/api/workflows/wf-exp-1/exports/{job_id}").get_json()
        assert body["status"] == "success"
        assert body["downloadable"] is True
        assert body["row_count"] == 2
        assert captured["name"].startswith(f"exports/wf-exp-1/{job_id}/")

        # Download streams the stored file as an attachment.
        with patch(
            "project.api.workflows.routes.storage.download_bytes",
            return_value=captured["data"],
        ):
            d = client.get(f"/api/workflows/wf-exp-1/exports/{job_id}/download")
        assert d.status_code == 200
        assert "attachment" in d.headers["Content-Disposition"]
        assert d.data == captured["data"]

    def test_download_missing_job_404(self, client, login, wf_env):
        login(wf_env["user"].email)
        r = client.get("/api/workflows/wf-exp-1/exports/does-not-exist/download")
        assert r.status_code == 404


class TestPurgeExpired:
    def test_purges_expired_file_and_row(self, app, wf_env):
        from project import db
        from project.db_models.export_models import ExportJob
        from project.services import workflow_exports as we

        db.session.add(
            ExportJob(
                job_id="exp-old",
                workflow_run_id=wf_env["wf"].id,
                output_key="forecast_results",
                fmt="csv",
                status="success",
                object_path="mst-artifacts/exports/wf-exp-1/exp-old/f.csv",
                created_at=datetime.now(timezone.utc) - timedelta(hours=48),
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        db.session.commit()

        with patch("project.services.workflow_exports.storage.remove_prefix") as m:
            removed = we.purge_expired()

        assert removed == 1
        m.assert_called_once_with("exports/wf-exp-1/exp-old/")
        assert ExportJob.query.filter_by(job_id="exp-old").first() is None
