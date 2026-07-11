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


def test_facets_cached_after_first_call(app, monkeypatch):
    with app.app_context():
        fr = _seed_run()
        calls = {"n": 0}
        real_results_df = svc.results_df

        def counting_results_df(fr_):
            calls["n"] += 1
            return real_results_df(fr_)

        monkeypatch.setattr(svc, "results_df", counting_results_df)

        # Two different columns, two calls — but only ONE df load (facets cached).
        svc.distinct_for_column(fr, "sector")
        svc.distinct_for_column(fr, "scenario")
        assert calls["n"] == 1


def test_inprogress_run_not_cached(app, monkeypatch):
    with app.app_context():
        fr = _seed_run(status="running")
        calls = {"n": 0}
        real_results_df = svc.results_df

        def counting_results_df(fr_):
            calls["n"] += 1
            return real_results_df(fr_)

        monkeypatch.setattr(svc, "results_df", counting_results_df)
        svc.distinct_for_column(fr, "sector")
        svc.distinct_for_column(fr, "scenario")
        assert calls["n"] == 2  # not cached while status != success


def test_invalidate_facets_clears_cache(app):
    from project import cache

    with app.app_context():
        fr = _seed_run()
        svc.distinct_for_column(fr, "sector")  # populate cache
        assert cache.get(f"forecast_facets:{fr.run_id}") is not None
        svc.invalidate_facets(fr.run_id)
        assert cache.get(f"forecast_facets:{fr.run_id}") is None


def test_promoted_columns_exist_and_writable(app):
    # Task 6: sector/subsector/country/scenario are promoted from meta_json into
    # real indexed columns so filter-dropdown distinct queries can be answered
    # by an indexed SELECT DISTINCT instead of loading the whole run into pandas.
    with app.app_context():
        fr = _seed_run(n_per_sector=1)
        row = ForecastRunResult(
            forecast_run_id=fr.id,
            date="2030-01-01",
            predicted=1.0,
            segment_key="seg_Energy",
            sector="Energy",
            subsector="Oil & Gas",
            country="US",
            scenario="Adverse",
        )
        db.session.add(row)
        db.session.commit()

        fetched = ForecastRunResult.query.filter_by(id=row.id).one()
        assert fetched.sector == "Energy"
        assert fetched.subsector == "Oil & Gas"
        assert fetched.country == "US"
        assert fetched.scenario == "Adverse"

        index_names = {ix.name for ix in ForecastRunResult.__table__.indexes}
        assert index_names.issuperset(
            {
                "ix_frr_run_sector",
                "ix_frr_run_subsector",
                "ix_frr_run_country",
                "ix_frr_run_scenario",
            }
        )


def test_promoted_dims_from_meta_extracts_known_keys():
    from project.services.forecast_runs import promoted_dims_from_meta

    meta = {"sector": "Tech", "scenario": "Adverse", "irrelevant": "x"}
    assert promoted_dims_from_meta(meta) == {"sector": "Tech", "scenario": "Adverse"}
    # a promoted key present but None is dropped, not carried as a null column
    assert promoted_dims_from_meta({"sector": "X", "country": None}) == {"sector": "X"}


def test_forecast_result_mappings_populates_promoted_columns():
    from project.workers.forecast import _forecast_result_mappings

    meta_rows = [
        {
            "date": "2030-01-01",
            "sector": "Energy",
            "country": "US",
            "scenario": "Baseline",
        },
        {
            "date": "2031-01-01",
            "sector": "Energy",
            "country": "US",
            "scenario": "Adverse",
        },
    ]
    mappings = _forecast_result_mappings(42, [1.5, 2.5], meta_rows, "seg_energy")

    assert len(mappings) == 2
    m0 = mappings[0]
    # promoted columns populated from meta
    assert m0["sector"] == "Energy"
    assert m0["country"] == "US"
    assert m0["scenario"] == "Baseline"
    # segment_key set once from the explicit param, not duplicated/overridden
    assert m0["segment_key"] == "seg_energy"
    # unchanged fields preserved
    assert m0["forecast_run_id"] == 42
    assert m0["date"] == "2030-01-01"
    assert m0["predicted"] == 1.5
    # meta_json still holds the full row meta
    import json

    assert json.loads(m0["meta_json"])["sector"] == "Energy"
    # second row's scenario differs
    assert mappings[1]["scenario"] == "Adverse"
