"""Materialised analysis-series reader helpers (Heatmap / Financial Forecast).

The endpoints read pre-computed level series from credit_risk_analysis_series
instead of recomputing from MinIO + pandas. These tests cover the reader/loader
helpers against directly-inserted rows (no MinIO), plus lazy-backfill wiring.
"""

from project import db
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
