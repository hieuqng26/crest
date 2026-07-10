"""Materialise the level series that the Sector Heatmap & Financial Forecast pages
read, so those pages don't recompute them from MinIO + pandas on every request.

The heavy lifting (portfolio load, forecast-index build, per-client aggregation)
lives in ``project.services.credit_risk_analysis``. To guarantee the stored numbers
are byte-identical to what the on-demand endpoints produce, we reuse those exact
helpers here rather than re-deriving the math — this module only decides *which*
scopes/slots/scenarios to enumerate and shapes the rows for bulk insert.

Called once per successful credit-analysis run (from ``run_credit_analysis``) and,
as a lazy fallback, on first read of a run that predates this feature.
"""

from __future__ import annotations

import pandas as pd

# Slots that feed the two Analysis pages (superset of the forecast page's targets;
# revenue/cogs/debts are what the heatmap ratios need).
_ANALYSIS_SLOTS = [
    "total_assets",
    "short_term_debts",
    "long_term_debts",
    "total_revenue",
    "total_cogs",
]

_HISTORY_SCENARIO = "History"


def build_analysis_series_rows(
    cr, portfolio_df: pd.DataFrame, slots: dict
) -> list[dict]:
    """Return CreditRiskAnalysisSeries row-dicts for one credit-analysis run.

    ``slots`` maps slot_key → ForecastRun (as produced by ``_slot_forecast_runs``).
    Reuses the endpoint helpers so the stored level series matches the live math.
    """
    # Imported lazily to avoid a circular import at module load (the service
    # imports the worker's tasks, which import this module).
    from project.services.credit_risk_analysis import (
        all_scenarios,
        historical_series,
        variable_levels,
    )

    if "sector" not in portfolio_df.columns:
        return []

    run_pk = cr.id
    rows: list[dict] = []
    # One memo for the whole materialisation: the parsed historical frames and
    # forecast indexes are reused across every sector/client iteration below
    # (this replaces the request-scoped flask.g memoization the helpers had
    # when they lived on the routes).
    memo: dict = {}

    def _emit(scope_type, scope_key, sector, slot, scenario, is_history, levels):
        for yr, val in levels.items():
            rows.append(
                {
                    "credit_risk_run_id": run_pk,
                    "scope_type": scope_type,
                    "scope_key": str(scope_key),
                    "sector": sector,
                    "slot": slot,
                    "scenario": scenario,
                    "is_history": is_history,
                    "year": int(yr),
                    "value": None if val is None else float(val),
                }
            )

    sectors = sorted(portfolio_df["sector"].dropna().unique().tolist())

    for slot in _ANALYSIS_SLOTS:
        fr = slots.get(slot)
        if not fr:
            continue
        scenarios = all_scenarios(fr, memo)

        # ── sector scope ──────────────────────────────────────────────────────
        for sector in sectors:
            sector_rows = portfolio_df[portfolio_df["sector"] == sector]
            hist = historical_series(fr, sector, None, memo)
            _emit("sector", sector, None, slot, _HISTORY_SCENARIO, True, hist)
            for scen in scenarios:
                levels = variable_levels(sector_rows, fr, scen, {}, memo)
                _emit("sector", sector, None, slot, scen, False, levels)

        # ── client scope ──────────────────────────────────────────────────────
        for (sector, client_id), client_df in portfolio_df.groupby(
            ["sector", "client_id"], sort=False
        ):
            cid = str(client_id)
            hist = historical_series(fr, None, cid, memo)
            _emit("client", cid, str(sector), slot, _HISTORY_SCENARIO, True, hist)
            for scen in scenarios:
                levels = variable_levels(client_df, fr, scen, {}, memo)
                _emit("client", cid, str(sector), slot, scen, False, levels)

    return rows


def materialize_analysis_series(cr, portfolio_df: pd.DataFrame, slots: dict) -> int:
    """Compute and persist the analysis level series for ``cr`` (replacing any
    existing rows for that run). Returns the number of rows written. Runs inside an
    app context / session provided by the caller."""
    from project import db
    from project.db_models.credit_models import CreditRiskAnalysisSeries

    CreditRiskAnalysisSeries.query.filter_by(credit_risk_run_id=cr.id).delete()
    rows = build_analysis_series_rows(cr, portfolio_df, slots)
    if rows:
        db.session.bulk_insert_mappings(CreditRiskAnalysisSeries, rows)
    db.session.commit()
    return len(rows)
