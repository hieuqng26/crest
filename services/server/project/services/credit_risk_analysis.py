"""Credit-risk analysis reads and series loaders (transport-agnostic).

Backs the Sector Heatmap / Financial Forecast screens and the MCP analysis
tools, and provides the level-series builders the Celery materializer
(``core/credit_risk/analysis_series.py``) reuses so the stored numbers stay
byte-identical to the live math.

Both screens read from a CreditRiskRun: its credit + financial-portfolio
datasets (for sector/subsector/country routing, same merge the Celery task
does) and its linked ForecastRun "slots". total_assets / short_term_debts /
long_term_debts are the 3 slots required to run KMV at all; total_revenue and
total_cogs are optional extra slots that unlock these two Analysis screens.
"History" comes from the actual dataset each forecast run's calibration was
trained on (real historical actuals), not mocked.

No Flask imports. Where the old route helpers memoized on ``flask.g``, these
take an explicit ``memo`` dict instead — pass one dict across a batch of calls
(the materializer loops over every sector/client) to get the same "parse the
dataset once" behaviour; omit it for one-off calls.
"""

import pandas as pd

from project import cache, db
from project.core import dataset_io
from project.core.credit_risk.forecast_lookup import (
    build_variable_index,
    lookup_forecast,
)
from project.db_models.calibration_models import CalibrationRun, Dataset
from project.db_models.credit_models import (
    CreditRiskAnalysisSeries,
    CreditRiskForecastInput,
    CreditRiskRun,
)
from project.db_models.forecast_models import ForecastRun
from project.exceptions import BadRequestError, NotFoundError
from project.services import credit_analysis


class AnalysisSeriesPending(Exception):
    """Raised when a run's Heatmap / Forecast level series isn't materialised yet.

    Carries the run so the boundary can dispatch the Celery backfill (via
    ``series_pending_payload``) and answer 202 — the request never blocks on
    the heavy pandas job (which is what made these pages slow / stall).
    """

    def __init__(self, run: CreditRiskRun):
        super().__init__("Analysis series not materialised yet")
        self.run = run


def load_dataset_df(dataset: Dataset, memo: dict | None = None) -> pd.DataFrame:
    """Download + parse a Dataset's file from MinIO — same object-key convention
    as the credit-risk analysis Celery task (``run_credit_analysis``).

    Cached cross-request under ``cr_dataset_df:<id>:<file_path>`` (a dataset's
    file is immutable per file_path — a re-upload gets a new path — so the entry
    never goes stale and only needs a TTL for memory hygiene), plus the optional
    caller ``memo`` so a batch caller pays the cache round-trip once.
    """
    memo_key = ("dataset_df", dataset.id)
    if memo is not None and memo_key in memo:
        return memo[memo_key]

    xcache_key = f"cr_dataset_df:{dataset.id}:{dataset.file_path}"
    df = cache.get(xcache_key)
    if df is None:
        df = dataset_io.download_dataset_df(dataset)
        cache.set(xcache_key, df, timeout=3600)

    if memo is not None:
        memo[memo_key] = df
    return df


def get_analysis_run(run_id: str | None) -> CreditRiskRun:
    """The requested run, or the active one when ``run_id`` is None.

    Raises ``NotFoundError`` (404) if absent or not successfully completed.
    """
    cr = (
        CreditRiskRun.query.filter_by(run_id=run_id).first()
        if run_id
        else CreditRiskRun.query.filter_by(is_active=True).first()
    )
    if not cr:
        raise NotFoundError(
            "No active credit risk run" if not run_id else "Run not found"
        )
    if cr.status != "success":
        raise NotFoundError("This run has not completed successfully")
    return cr


def slot_forecast_runs(cr: CreditRiskRun) -> dict[str, ForecastRun]:
    """slot_key → successful ForecastRun for a run's linked forecast inputs."""
    slots = {}
    for inp in CreditRiskForecastInput.query.filter_by(credit_risk_run_id=cr.id).all():
        fr = ForecastRun.query.get(inp.forecast_run_id)
        if fr and fr.status == "success":
            slots[inp.slot] = fr
    return slots


def analysis_portfolio_df(cr: CreditRiskRun) -> pd.DataFrame:
    """The run's credit portfolio, with the financial-portfolio meta columns
    (country/sector/subsector) merged in — the same merge the Celery task does.

    Raises ``ValueError`` when the credit dataset is gone: only the workers
    call this (the endpoints read the materialised series), and they treat any
    failure as "skip materialisation", not as a client-facing DomainError.
    """
    credit_ds = Dataset.query.get(cr.dataset_id)
    if not credit_ds or not credit_ds.file_path:
        raise ValueError("Credit dataset not found")
    portfolio_df = load_dataset_df(credit_ds)

    if cr.financial_portfolio_dataset_id:
        fin_ds = Dataset.query.get(cr.financial_portfolio_dataset_id)
        if fin_ds and fin_ds.file_path:
            fin_df = load_dataset_df(fin_ds)
            meta_cols = [
                c
                for c in ("client_id", "country", "sector", "subsector")
                if c in fin_df.columns
            ]
            if "client_id" in meta_cols:
                fin_meta = fin_df[meta_cols].drop_duplicates(subset=["client_id"])
                new_cols = ["client_id"] + [
                    c
                    for c in meta_cols
                    if c != "client_id" and c not in portfolio_df.columns
                ]
                portfolio_df = portfolio_df.merge(
                    fin_meta[new_cols], on="client_id", how="left"
                )
    return portfolio_df


def historical_series(
    fr: ForecastRun,
    sector: str | None,
    client_id: str | None,
    memo: dict | None = None,
) -> dict:
    """Actual historical {year: summed target value} from the dataset this forecast
    run's calibration was trained on — filtered to one client, or summed across a
    whole sector. The materializer calls this once per sector/client, so the
    expensive part (date parsing) is memoized per calibration run on ``memo`` —
    only the cheap boolean-filter + groupby repeats per call."""
    # Memoize the resolved CalibrationRun per forecast run — the bare .get()
    # would otherwise re-fire that identical query for every sector/client.
    cal_key = ("cal_run", fr.id)
    cal_run = memo.get(cal_key) if memo is not None else None
    if cal_run is None:
        cal_run = CalibrationRun.query.get(fr.calibration_run_id)
        if memo is not None:
            memo[cal_key] = cal_run if cal_run is not None else False
    elif cal_run is False:
        return {}
    if not cal_run or not cal_run.target_col:
        return {}
    target = cal_run.target_col

    frame_key = ("hist_frame", cal_run.id)
    work = memo.get(frame_key) if memo is not None else None
    if work is None:

        def _remember(frame):
            if memo is not None:
                memo[frame_key] = frame
            return frame

        ds = Dataset.query.get(cal_run.dataset_id)
        if not ds or not ds.file_path:
            work = _remember(pd.DataFrame())
            return {}
        try:
            df = load_dataset_df(ds, memo)
        except Exception:
            work = _remember(pd.DataFrame())
            return {}
        date_col = next(
            (c for c in ("date", "YEAR", "year", "period") if c in df.columns), None
        )
        if not date_col or target not in df.columns:
            work = _remember(pd.DataFrame())
            return {}
        work = df.copy()
        work["_year"] = pd.to_datetime(work[date_col], errors="coerce").dt.year
        if work["_year"].isna().all():
            # Already a bare year column (e.g. int 2024)
            work["_year"] = pd.to_numeric(df[date_col], errors="coerce")
        work = _remember(work.dropna(subset=["_year"]))

    if work.empty or target not in work.columns:
        return {}
    if client_id and "client_id" in work.columns:
        subset = work[work["client_id"] == client_id]
    elif sector and "sector" in work.columns:
        subset = work[work["sector"] == sector]
    else:
        subset = work
    if subset.empty:
        return {}
    grouped = subset.groupby("_year")[target].sum()
    return {int(y): float(v) for y, v in grouped.items()}


def cached_variable_index(
    fr: ForecastRun, memo: dict | None = None
) -> tuple[dict, dict]:
    """Memoized ``build_variable_index`` — the materializer calls this once per
    client row (dozens to hundreds per run); rebuilding the segmentation info +
    prediction index from ForecastRunResult rows each time would be an N+1 query
    pattern.

    Cached on the caller ``memo`` and, for successful runs, on the cross-request
    app ``cache`` under ``cr_var_index:<run_id>`` — the exact key the
    segment-recompute worker deletes to invalidate (do not rename)."""
    memo_key = ("var_index", fr.id)
    if memo is not None and memo_key in memo:
        return memo[memo_key]

    xcache_key = f"cr_var_index:{fr.run_id}"
    result = cache.get(xcache_key) if fr.status == "success" else None
    if result is None:
        result = build_variable_index(fr)
        if fr.status == "success":
            cache.set(xcache_key, result, timeout=3600)

    if memo is not None:
        memo[memo_key] = result
    return result


def variable_levels(
    rows_df: pd.DataFrame,
    fr: ForecastRun,
    scenario: str,
    hist: dict,
    memo: dict | None = None,
) -> dict:
    """{year: value} — historical actuals merged with the forecast sum across every
    row in rows_df (one sector's clients, or a single client) for one scenario."""
    seg_info, idx_map = cached_variable_index(fr, memo)
    totals: dict[int, float] = {}
    for _, r in rows_df.iterrows():
        series = lookup_forecast(
            seg_info,
            idx_map,
            str(r.get("sector") or ""),
            str(r.get("subsector") or ""),
            str(r.get("country") or ""),
        )
        for yr, v in series.get(scenario, {}).items():
            totals[yr] = totals.get(yr, 0.0) + v
    levels = dict(hist)
    levels.update(totals)
    return levels


def all_scenarios(fr: ForecastRun, memo: dict | None = None) -> list[str]:
    _, idx_map = cached_variable_index(fr, memo)
    scens: set[str] = set()
    for ctx_map in idx_map.values():
        scens.update(ctx_map.keys())
    order = {"Baseline": 0, "Adverse": 1, "Severely Adverse": 2}
    return sorted(scens, key=lambda s: (order.get(s, 99), s))


def dispatch_series_backfill(cr: CreditRiskRun) -> None:
    """Enqueue the analysis-series backfill once, deduped across concurrent pollers.

    ``cache.add`` sets the lock only if absent, so overlapping heatmap/forecast/meta
    requests (and repeated poll ticks) enqueue the task a single time. The lock TTL
    doubles as a cooldown: if the backfill fails, we won't re-enqueue for 10 min.
    On success the run has rows, so this path isn't reached again regardless.
    """
    from project.workers.tasks import backfill_analysis_series

    if cache.add(f"cr_series_backfill:{cr.run_id}", 1, timeout=600):
        backfill_analysis_series.delay(cr.run_id)


def series_pending_payload(cr: CreditRiskRun) -> dict:
    """Dispatch the backfill and shape the "come back later" payload the caller
    returns (HTTP 202 / MCP status field)."""
    dispatch_series_backfill(cr)
    return {
        "status": "materializing",
        "message": "Preparing analysis data — this run's series is being computed. "
        "This page will refresh automatically.",
    }


def analysis_series_materialised(cr: CreditRiskRun) -> bool:
    """Cheap existence probe (one indexed row) — distinguishes an un-materialised
    run from a legitimately-empty scope so callers can return 202 vs 404 correctly."""
    return (
        db.session.query(CreditRiskAnalysisSeries.id)
        .filter(CreditRiskAnalysisSeries.credit_risk_run_id == cr.id)
        .first()
        is not None
    )


def load_analysis_series(
    cr: CreditRiskRun, *, scope_type=None, scope_key=None, scope_keys=None, sector=None
):
    """Return the materialised level series for a run as a nested dict:

        series[scope_type][scope_key][slot][scenario] = {year: value}

    plus ``sector_of`` mapping each client scope_key → its sector. Reads exclusively
    from ``credit_risk_analysis_series`` with a lightweight column SELECT — never the
    whole ORM row — and only the scope the caller needs (the heatmap overview wants
    just ``scope_type='sector'``; the forecast wants a single scope_key). Loading the
    entire run's rows was the cost that made these pages slow. If the run isn't
    materialised yet, raises ``AnalysisSeriesPending`` so the caller returns 202.
    """
    if not analysis_series_materialised(cr):
        raise AnalysisSeriesPending(cr)

    m = CreditRiskAnalysisSeries
    q = db.session.query(
        m.scope_type, m.scope_key, m.sector, m.slot, m.scenario, m.year, m.value
    ).filter(m.credit_risk_run_id == cr.id)
    if scope_type is not None:
        q = q.filter(m.scope_type == scope_type)
    if scope_key is not None:
        q = q.filter(m.scope_key == scope_key)
    if scope_keys is not None:
        q = q.filter(m.scope_key.in_(list(scope_keys)))
    if sector is not None:
        q = q.filter(m.sector == sector)

    series: dict = {}
    sector_of: dict[str, str] = {}
    for st, sk, sec, slot, scen, year, value in q.all():
        series.setdefault(st, {}).setdefault(sk, {}).setdefault(slot, {}).setdefault(
            scen, {}
        )[year] = value
        if st == "client" and sec is not None:
            sector_of[sk] = sec
    return series, sector_of


def get_analysis_meta(run_id: str | None = None) -> dict:
    """Sectors, companies and available metrics for a run's Analysis screens.

    Raises ``NotFoundError`` (404) / ``AnalysisSeriesPending`` (202).
    """
    cr = get_analysis_run(run_id)

    # Sectors, companies and linked forecast targets are fixed for a run (a segment
    # re-fit changes values, not membership), so cache the whole payload per run —
    # only the first hit pays the distinct scan over the client-scope rows.
    cache_key = f"cr_analysis_meta:{cr.run_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    slots = slot_forecast_runs(cr)

    # Sectors and their companies come straight from the materialised series
    # (distinct client scope_keys + their sector) — an indexed SELECT, instead of
    # downloading and parsing the portfolio from MinIO on every page load.
    pairs = (
        db.session.query(
            CreditRiskAnalysisSeries.scope_key, CreditRiskAnalysisSeries.sector
        )
        .filter(
            CreditRiskAnalysisSeries.credit_risk_run_id == cr.id,
            CreditRiskAnalysisSeries.scope_type == "client",
            CreditRiskAnalysisSeries.sector.isnot(None),
        )
        .distinct()
        .all()
    )
    if not pairs:
        raise AnalysisSeriesPending(cr)

    companies_by_sector: dict[str, list[str]] = {}
    for client_id, sector in pairs:
        companies_by_sector.setdefault(str(sector), []).append(str(client_id))
    for sector in companies_by_sector:
        companies_by_sector[sector] = sorted(set(companies_by_sector[sector]))

    payload = {
        "run_id": cr.run_id,
        "sectors": sorted(companies_by_sector.keys()),
        "companies_by_sector": companies_by_sector,
        "forecast_targets": [
            {"key": key, "title": title}
            for key, title in credit_analysis.FORECAST_TARGET_SLOTS
            if key in slots
        ],
        "available_metrics": {
            k: k in slots
            for k in (
                "total_assets",
                "short_term_debts",
                "long_term_debts",
                "total_revenue",
                "total_cogs",
            )
        },
    }
    cache.set(cache_key, payload, timeout=3600)
    return payload


def get_analysis_heatmap(
    metric: str,
    run_id: str | None = None,
    sector: str | None = None,
    clients: set[str] | None = None,
    scenario: str | None = None,
) -> dict:
    """Sector overview (no ``sector``) or client drill-down heatmap payload.

    Raises ``BadRequestError`` (400, unknown metric) / ``NotFoundError`` (404) /
    ``AnalysisSeriesPending`` (202).
    """
    if metric not in credit_analysis.HEATMAP_METRICS:
        raise BadRequestError(f"Unknown metric '{metric}'")

    cr = get_analysis_run(run_id)
    # Load only the scope this view needs: the sector overview reads sector-scope
    # rows; a drilldown reads just the selected companies' client-scope rows.
    # (Loading the whole run's rows is what made this endpoint slow.)
    if sector:
        series, sector_of = load_analysis_series(
            cr,
            scope_type="client",
            scope_keys=clients,
            sector=None if clients else sector,
        )
    else:
        series, sector_of = load_analysis_series(cr, scope_type="sector")
    slots = slot_forecast_runs(cr)

    return credit_analysis.build_heatmap(
        series,
        sector_of,
        slots,
        metric=metric,
        sector_filter=sector,
        client_filter=clients,
        requested_scenario=scenario,
    )


def get_analysis_forecast(
    sector: str,
    run_id: str | None = None,
    client_id: str | None = None,
    requested_keys: set[str] | None = None,
    indexed: bool = False,
) -> dict:
    """Financial-forecast payload for one sector (or one of its clients).

    Raises ``BadRequestError`` (400) / ``NotFoundError`` (404) /
    ``AnalysisSeriesPending`` (202).
    """
    if not sector:
        raise BadRequestError("sector is required")

    # Scope: a single company if client_id given, else the whole sector — load only
    # that scope's rows rather than the entire run's.
    scope_type, scope_key = ("client", client_id) if client_id else ("sector", sector)

    cr = get_analysis_run(run_id)
    series, _ = load_analysis_series(cr, scope_type=scope_type, scope_key=scope_key)
    slots = slot_forecast_runs(cr)

    return credit_analysis.build_forecast(
        series,
        slots,
        sector=sector,
        client_id=client_id,
        requested_keys=requested_keys,
        indexed=indexed,
    )
