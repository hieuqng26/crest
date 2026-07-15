"""Materialised analysis-series reader helpers (Heatmap / Financial Forecast).

The endpoints read pre-computed level series from credit_risk_analysis_series
instead of recomputing from MinIO + pandas. These tests cover the reader/loader
helpers against directly-inserted rows (no MinIO), plus lazy-backfill wiring.
"""

import pandas as pd

from project import db
from project.core.credit_risk import analysis_series as AS
from project.services import credit_analysis as CA
from project.services import credit_risk_analysis as R
from project.db_models.credit_models import CreditRiskAnalysisSeries, CreditRiskRun


def _make_run(status="success"):
    cr = CreditRiskRun(
        run_id="test-run-series",
        dataset_id=1,
        is_active=True,
        exposure=1.0,
        discount_rate=0.05,
        lifetime_horizon=5,
        curve="moodys",
        status=status,
    )
    db.session.add(cr)
    db.session.commit()
    return cr


def _add(cr, scope_type, scope_key, sector, slot, scenario, is_history, yv):
    for y, v in yv.items():
        db.session.add(
            CreditRiskAnalysisSeries(
                credit_risk_run_id=cr.id,
                scope_type=scope_type,
                scope_key=scope_key,
                sector=sector,
                slot=slot,
                scenario=scenario,
                is_history=is_history,
                year=y,
                value=v,
            )
        )


def test_table_in_metadata(app):
    assert "credit_risk_analysis_series" in db.metadata.tables


def test_load_and_read_series(app):
    with app.app_context():
        cr = _make_run()
        _add(
            cr, "sector", "Tech", None, "total_revenue", "History", True, {2020: 100.0}
        )
        _add(
            cr,
            "sector",
            "Tech",
            None,
            "total_revenue",
            "Baseline",
            False,
            {2021: 110.0, 2022: 121.0},
        )
        _add(cr, "client", "C1", "Tech", "total_revenue", "History", True, {2020: 40.0})
        _add(
            cr, "client", "C1", "Tech", "total_revenue", "Baseline", False, {2021: 44.0}
        )
        db.session.commit()

        series, sector_of = R.load_analysis_series(cr)
        assert sector_of == {"C1": "Tech"}
        assert CA.series_levels(
            series, "sector", "Tech", "total_revenue", "Baseline"
        ) == {2021: 110.0, 2022: 121.0}
        assert CA.series_levels(
            series, "sector", "Tech", "total_revenue", CA.SERIES_HISTORY
        ) == {2020: 100.0}
        # missing scope returns empty dict, not error
        assert (
            CA.series_levels(series, "client", "NOPE", "total_revenue", "Baseline")
            == {}
        )


class _FR:
    """Stand-in ForecastRun — the mocked helpers ignore its contents."""

    def __init__(self, i):
        self.id = i


def _mock_helpers(monkeypatch):
    monkeypatch.setattr(R, "all_scenarios", lambda fr, memo=None: ["Baseline"])
    monkeypatch.setattr(
        R, "historical_series", lambda fr, sector, cid, memo=None: {2020: 1.0}
    )
    monkeypatch.setattr(
        R, "variable_levels", lambda rows, fr, scen, opts, memo=None: {2021: 2.0}
    )


def test_build_rows_emits_progress(app, monkeypatch):
    """build_analysis_series_rows still produces rows and now reports per-slot /
    per-client progress (with a build fraction) through the on_progress callback
    (mocking the heavy MinIO-backed helpers so the test stays offline)."""
    _mock_helpers(monkeypatch)

    class _Cr:
        id = 42

    portfolio_df = pd.DataFrame(
        {
            "sector": ["Tech", "Tech", "Ind"],
            "client_id": ["C1", "C2", "C3"],
        }
    )
    slots = {"total_assets": _FR(1), "total_revenue": _FR(2)}

    msgs = []
    rows = AS.build_analysis_series_rows(
        _Cr(), portfolio_df, slots, on_progress=lambda m, f: msgs.append((m, f))
    )

    # Rows are still produced (2 slots × [sector + client scopes] × years).
    assert rows and all(r["credit_risk_run_id"] == 42 for r in rows)
    # One "Building …" header per present slot, tagged with slot + position.
    headers = [m for m, _ in msgs if m.startswith("Building analysis views")]
    assert headers == [
        "Building analysis views for 'total_assets' (1/2)",
        "Building analysis views for 'total_revenue' (2/2)",
    ]
    # The final client line of the last slot is emitted (was previously skipped) and
    # reports the full build fraction.
    client_lines = [(m, f) for m, f in msgs if "aggregated" in m]
    assert client_lines[-1][0] == "'total_revenue': aggregated 3/3 clients"
    assert client_lines[-1][1] == 1.0
    # Build fraction is monotonically non-decreasing.
    fracs = [f for _, f in msgs]
    assert fracs == sorted(fracs)


def test_materialize_chunks_insert_and_reports_progress(app, monkeypatch):
    """materialize_analysis_series persists the rows and reports an overall
    fraction that ends at 1.0, with a row-count line for the insert phase."""
    _mock_helpers(monkeypatch)
    with app.app_context():
        cr = _make_run()
        portfolio_df = pd.DataFrame(
            {"sector": ["Tech", "Tech", "Ind"], "client_id": ["C1", "C2", "C3"]}
        )
        slots = {"total_assets": _FR(1), "total_revenue": _FR(2)}

        msgs = []
        n = AS.materialize_analysis_series(
            cr, portfolio_df, slots, on_progress=lambda m, f: msgs.append((m, f))
        )

        # Rows were actually written for this run.
        assert n > 0
        assert (
            CreditRiskAnalysisSeries.query.filter_by(credit_risk_run_id=cr.id).count()
            == n
        )
        # The (previously silent) insert phase now reports a row-count line…
        insert_lines = [m for m, _ in msgs if m.startswith("Materialised")]
        assert (
            insert_lines and insert_lines[-1] == f"Materialised {n:,}/{n:,} series rows"
        )
        # …and the overall fraction reaches 1.0 at completion.
        assert msgs[-1][1] == 1.0


def test_build_rows_no_sector_column_is_empty(app):
    """A portfolio without a sector column yields no series and no crash."""

    class _Cr:
        id = 1

    df = pd.DataFrame({"client_id": ["C1"]})
    assert AS.build_analysis_series_rows(_Cr(), df, {}) == []


def test_combined_history_plus_baseline(app):
    """The heatmap merges history then overlays baseline (baseline wins on overlap)."""
    with app.app_context():
        cr = _make_run()
        _add(
            cr,
            "sector",
            "Ind",
            None,
            "total_revenue",
            "History",
            True,
            {2019: 90.0, 2020: 100.0},
        )
        _add(
            cr,
            "sector",
            "Ind",
            None,
            "total_revenue",
            "Baseline",
            False,
            {2020: 105.0, 2021: 115.0},
        )
        db.session.commit()

        series, _ = R.load_analysis_series(cr)
        combined = dict(
            CA.series_levels(
                series, "sector", "Ind", "total_revenue", CA.SERIES_HISTORY
            )
        )
        combined.update(
            CA.series_levels(series, "sector", "Ind", "total_revenue", "Baseline")
        )
        assert combined == {2019: 90.0, 2020: 105.0, 2021: 115.0}
