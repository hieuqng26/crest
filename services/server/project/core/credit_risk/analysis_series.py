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

# Materialisation has two sub-phases with very different durations: building the
# rows in memory (per-client pandas aggregation, seconds) and bulk-inserting them
# (can be minutes for a large portfolio). We report one 0→1 fraction across both so
# a caller can drive a single progress bar; the insert dominates wall-clock time,
# so it gets the larger share of the fraction.
_BUILD_FRACTION = 0.25
_INSERT_CHUNK = 50_000


def build_analysis_series_rows(
    cr, portfolio_df: pd.DataFrame, slots: dict, on_progress=None
) -> list[dict]:
    """Return CreditRiskAnalysisSeries row-dicts for one credit-analysis run.

    ``slots`` maps slot_key → ForecastRun (as produced by ``_slot_forecast_runs``).
    Reuses the endpoint helpers so the stored level series matches the live math.

    ``on_progress(message, frac)`` — optional callback invoked with human-readable
    progress lines as each slot's sector/client scopes are aggregated, where ``frac``
    is this build phase's completion in [0, 1]. This is the first sub-phase of the
    long, "Finalizing" tail of a credit run. Failures in the callback must never
    break materialisation, so the caller is expected to keep it silent-failing.
    """
    # Imported lazily to avoid a circular import at module load (the service
    # imports the worker's tasks, which import this module).
    from project.services.credit_risk_analysis import (
        all_scenarios,
        historical_series,
        variable_levels,
    )

    def _progress(message: str, frac: float):
        if on_progress:
            on_progress(message, frac)

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
    present_slots = [s for s in _ANALYSIS_SLOTS if slots.get(s)]
    n_slots = len(present_slots)

    # Group once (the sector/client_id grouping is slot-independent) and reuse the
    # sub-frames across every slot. Total build units = slots × clients, used to
    # report a single monotonic build fraction.
    client_groups = list(portfolio_df.groupby(["sector", "client_id"], sort=False))
    n_clients = len(client_groups)
    total_units = max(1, n_slots * n_clients)
    # Surface a client line ~every 20% within each slot (bounded regardless of size).
    step = max(1, n_clients // 5)
    done_units = 0

    for si, slot in enumerate(present_slots, 1):
        fr = slots[slot]
        scenarios = all_scenarios(fr, memo)
        _progress(
            f"Building analysis views for '{slot}' ({si}/{n_slots})",
            done_units / total_units,
        )

        # ── sector scope ──────────────────────────────────────────────────────
        for sector in sectors:
            sector_rows = portfolio_df[portfolio_df["sector"] == sector]
            hist = historical_series(fr, sector, None, memo)
            _emit("sector", sector, None, slot, _HISTORY_SCENARIO, True, hist)
            for scen in scenarios:
                levels = variable_levels(sector_rows, fr, scen, {}, memo)
                _emit("sector", sector, None, slot, scen, False, levels)

        # ── client scope (dominates build time) ───────────────────────────────
        for ci, ((sector, client_id), client_df) in enumerate(client_groups, 1):
            cid = str(client_id)
            hist = historical_series(fr, None, cid, memo)
            _emit("client", cid, str(sector), slot, _HISTORY_SCENARIO, True, hist)
            for scen in scenarios:
                levels = variable_levels(client_df, fr, scen, {}, memo)
                _emit("client", cid, str(sector), slot, scen, False, levels)
            done_units += 1
            # Log at each 20% mark and always at the final client of the slot.
            if ci % step == 0 or ci == n_clients:
                _progress(
                    f"'{slot}': aggregated {ci}/{n_clients} clients",
                    done_units / total_units,
                )

    return rows


def materialize_analysis_series(
    cr, portfolio_df: pd.DataFrame, slots: dict, on_progress=None
) -> int:
    """Compute and persist the analysis level series for ``cr`` (replacing any
    existing rows for that run). Returns the number of rows written. Runs inside an
    app context / session provided by the caller.

    ``on_progress(message, frac)`` receives progress lines with an overall
    completion fraction in [0, 1] spanning both the build and the bulk-insert
    sub-phases (the insert is chunked so it reports progress instead of blocking
    silently for minutes on a large portfolio)."""
    from project import db
    from project.db_models.credit_models import CreditRiskAnalysisSeries

    # Build phase maps onto [0, _BUILD_FRACTION] of the overall fraction.
    def _build_cb(message: str, frac: float):
        if on_progress:
            on_progress(message, _BUILD_FRACTION * frac)

    CreditRiskAnalysisSeries.query.filter_by(credit_risk_run_id=cr.id).delete()
    rows = build_analysis_series_rows(cr, portfolio_df, slots, on_progress=_build_cb)
    total = len(rows)
    if not total:
        db.session.commit()
        return 0

    # Insert phase maps onto (_BUILD_FRACTION, 1]. Chunk the bulk insert so a large
    # write reports incremental progress rather than one opaque multi-minute call.
    for start in range(0, total, _INSERT_CHUNK):
        db.session.bulk_insert_mappings(
            CreditRiskAnalysisSeries, rows[start : start + _INSERT_CHUNK]
        )
        db.session.flush()
        done = min(start + _INSERT_CHUNK, total)
        if on_progress:
            on_progress(
                f"Materialised {done:,}/{total:,} series rows",
                _BUILD_FRACTION + (1 - _BUILD_FRACTION) * done / total,
            )
    db.session.commit()
    return total
