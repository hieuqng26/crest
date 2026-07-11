"""distinct_for_column must return the same {values, truncated} shape regardless
of which implementation (df / cache / SQL) backs it. Seeded via bulk insert."""

import json


from project import db
from project.api.users.models import User
from project.db_models.calibration_models import CalibrationRun, Dataset, ModelConfig
from project.db_models.forecast_models import ForecastRun, ForecastRunResult
from project.services import forecast_runs as svc


def _seed_run(status="success", n_per_sector=5):
    # ForecastRun.calibration_run_id / dataset_id are NOT NULL FKs, so build the
    # minimal parent chain (user -> dataset -> model config -> calibration run)
    # before creating the forecast run itself.
    user = User(
        email="distinct-test@example.com",
        password="Passw0rd!",
        role="sysadmin",
        name="distinct-test",
    )
    user.status = "active"
    db.session.add(user)
    db.session.commit()

    ds = Dataset(
        name="fc-ds",
        source="upload",
        file_path="uploads/fc.csv",
        row_count=n_per_sector * 3,
        created_by=user.email,
        status="ready",
        kind="forecast",
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

    cal = CalibrationRun(
        run_id="cal-run-1",
        dataset_id=ds.id,
        model_config_id=cfg.id,
        status="success",
        triggered_by=user.email,
    )
    db.session.add(cal)
    db.session.commit()

    fr = ForecastRun(
        run_id="bench-run-1",
        status=status,
        calibration_run_id=cal.id,
        dataset_id=ds.id,
    )
    db.session.add(fr)
    db.session.flush()
    sectors = ["Energy", "Financials", "Tech"]
    rows = []
    for i in range(n_per_sector * len(sectors)):
        sector = sectors[i % len(sectors)]
        rows.append(
            {
                "forecast_run_id": fr.id,
                "date": f"2030-{(i % 12) + 1:02d}-01",
                "predicted": float(i),
                "segment_key": f"seg_{sector}",
                "meta_json": json.dumps(
                    {
                        "sector": sector,
                        "scenario": "Baseline",
                        "segment_key": f"seg_{sector}",
                    }
                ),
            }
        )
    db.session.bulk_insert_mappings(ForecastRunResult, rows)
    db.session.commit()
    return fr


def test_distinct_for_column_returns_sorted_capped_values(app):
    with app.app_context():
        fr = _seed_run()
        out = svc.distinct_for_column(fr, "sector")
        assert out["values"] == ["Energy", "Financials", "Tech"]
        assert out["truncated"] is False


def test_distinct_for_column_unknown_column_is_empty(app):
    with app.app_context():
        fr = _seed_run()
        out = svc.distinct_for_column(fr, "does_not_exist")
        assert out == {"values": [], "truncated": False}
