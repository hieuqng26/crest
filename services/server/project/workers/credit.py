import io
import json
from datetime import datetime, timezone

import pandas as pd

from project.core import storage
from project.workers import celery_app
from project.workers.common import (
    _cr_log,
    _load_df_by_dataset_id,
    _make_flask_app,
    _split_segment_key,
    format_failure,
)


from project.logger import get_logger

logger = get_logger(__name__)

# The credit run's 0–100 progress is split into two phases: the per-client KMV+ECL
# computation runs 0 → _CLIENT_COMPUTE_END, and the "Finalizing" analysis-series
# materialisation runs _CLIENT_COMPUTE_END → 100. The frontend stepper reads the
# same boundary to split the "Credit Analysis" vs "Complete" steps, so keep the two
# in sync (services/client/src/components/ui/WorkflowStepper.vue).
_CLIENT_COMPUTE_END = 80


def _compute_credit_for_clients(
    cr_run_id: str,
    clients_list: list,
    forecast_segmentation: dict,
    forecast_by_var: dict,
    pd_rating_df,
    exposure: float,
    discount_rate: float,
    lifetime_horizon: int,
    *,
    flush_every: int = 10,
    progress_base: int = 0,
    progress_span: int = 100,
) -> tuple[int, int]:
    """Run KMV + ECL for each client in `clients_list`, persisting a CreditRiskResult
    per client (with denormalised sector/subsector/country/segment_key so a single
    segment's rows can later be recomputed via an indexed WHERE). Returns
    (n_succeeded, n_failed).

    Shared by run_credit_analysis (whole portfolio) and recompute_segment_downstream
    (only the clients in one segment). `flush_every` batches the session commits; the
    per-segment recompute passes a large value so its small subset lands in one txn.
    Client→segment routing uses total_assets' seg_info as the canonical key source —
    the 3 required slots share one segmentation policy within a workflow submission.
    """
    from project import app_session
    from project.core.credit_risk.ecl import compute_ecl
    from project.core.credit_risk.forecast_lookup import (
        lookup_forecast,
        resolve_segment_key,
    )
    from project.core.credit_risk.kmv import run_kmv
    from project.db_models.credit_models import CreditRiskResult

    canonical_seg = forecast_segmentation.get("total_assets", {"split_by": {}})

    def _lookup(key: str, sector: str, subsector: str, country: str) -> dict:
        return lookup_forecast(
            forecast_segmentation[key],
            forecast_by_var[key],
            sector,
            subsector,
            country,
        )

    n_clients = len(clients_list)
    result_batch: list[CreditRiskResult] = []
    failed_clients = 0

    for idx, row in enumerate(clients_list):
        client_id = str(row["client_id"])
        com_info = {
            "E0": float(row["market_cap"]),
            "volE": float(row["vol_equity"]),
            "r": float(row["risk_free_rate"]),
            "rating": str(row["rating"]),
        }

        sector = str(row.get("sector") or "")
        subsector = str(row.get("subsector") or "")
        country = str(row.get("country") or "")
        # Canonical segment this client routes to — persisted for per-segment
        # recompute + Sector/Segment result filters. None for non-segmented runs.
        client_segment_key = (
            resolve_segment_key(canonical_seg, sector, subsector, country)
            if canonical_seg.get("split_by")
            else None
        )
        # Tags for this client's log lines (sector always known; segment only on
        # segmented runs).
        client_sector = sector or None
        client_segment = _split_segment_key(client_segment_key)[1]

        # Build forecast DataFrame from the 3 calibrated variable indices, routing
        # this client to its own segment's trajectory (segmented) or the single
        # portfolio-wide trajectory. Multi-scenario data is used directly; fall back
        # to a single "Baseline" when the data has no scenario dimension.
        ta_by_scen = _lookup("total_assets", sector, subsector, country)
        cl_by_scen = _lookup("short_term_debts", sector, subsector, country)
        nc_by_scen = _lookup("long_term_debts", sector, subsector, country)

        all_scens = sorted(set(ta_by_scen) & set(cl_by_scen) & set(nc_by_scen))
        if not all_scens:
            all_scens = ["Baseline"]
            ta_by_scen = {"Baseline": next(iter(ta_by_scen.values()), {})}
            cl_by_scen = {"Baseline": next(iter(cl_by_scen.values()), {})}
            nc_by_scen = {"Baseline": next(iter(nc_by_scen.values()), {})}

        rows_fc = []
        for scen in all_scens:
            ta_yr = ta_by_scen.get(scen, {})
            cl_yr = cl_by_scen.get(scen, {})
            nc_yr = nc_by_scen.get(scen, {})
            years = sorted(set(ta_yr) & set(cl_yr) & set(nc_yr))
            for yr in years:
                rows_fc.append(
                    {
                        "YEAR": yr,
                        "SCENARIO": scen,
                        "Total_Asset": ta_yr[yr],
                        "CL": cl_yr[yr],
                        "NonCL": nc_yr[yr],
                    }
                )

        if not rows_fc:
            failed_clients += 1
            _cr_log(
                cr_run_id,
                f"Client {client_id}: no overlapping forecast years across all 3 variables — skipping",
                level="warn",
                sector=client_sector,
                segment=client_segment,
            )
            continue
        forecast = pd.DataFrame(rows_fc)

        try:
            kmv_df = run_kmv(com_info, forecast, pd_rating_df)
            ecl_df = compute_ecl(kmv_df, exposure, discount_rate, lifetime_horizon)
            kmv_records = kmv_df.where(pd.notnull(kmv_df), None).to_dict(
                orient="records"
            )
            ecl_records = ecl_df.where(pd.notnull(ecl_df), None).to_dict(
                orient="records"
            )
            result_batch.append(
                CreditRiskResult(
                    run_id=cr_run_id,
                    client_id=client_id,
                    kmv_json=json.dumps(kmv_records),
                    ecl_json=json.dumps(ecl_records),
                    sector=sector or None,
                    subsector=subsector or None,
                    country=country or None,
                    segment_key=client_segment_key,
                )
            )
        except Exception as client_err:
            failed_clients += 1
            _cr_log(
                cr_run_id,
                f"Client {client_id} failed: {client_err}",
                level="warn",
                sector=client_sector,
                segment=client_segment,
            )

        # Flush batch and update progress every `flush_every` clients or at the end.
        if (idx + 1) % flush_every == 0 or idx == n_clients - 1:
            with app_session() as s:
                for res in result_batch:
                    s.add(res)
                result_batch = []
            progress = progress_base + round((idx + 1) / n_clients * progress_span)
            _cr_log(
                cr_run_id,
                f"Processed {idx + 1}/{n_clients} clients",
                progress=progress,
            )

    return n_clients - failed_clients, failed_clients


def _build_credit_portfolio_df(
    credit_dataset_id: int, financial_dataset_id: int | None
) -> "pd.DataFrame":
    """Rebuild the same credit+financial merged portfolio the full credit run uses
    (mirrors run_credit_analysis' load/merge), so per-segment recompute routes
    clients identically."""
    credit_df = _load_df_by_dataset_id(credit_dataset_id)
    if not financial_dataset_id:
        return credit_df
    fin_df = _load_df_by_dataset_id(financial_dataset_id)
    fin_meta = fin_df[["client_id", "country", "sector", "subsector"]].drop_duplicates(
        subset=["client_id"]
    )
    new_fin_cols = ["client_id"] + [
        c for c in fin_meta.columns if c != "client_id" and c not in credit_df.columns
    ]
    return credit_df.merge(fin_meta[new_fin_cols], on="client_id", how="left")


@celery_app.task(bind=True, name="run_credit_analysis")
def run_credit_analysis(self, cr_run_id: str):
    from project.workers.workflow import (
        advance_workflow,
    )  # deferred: avoids import cycle

    app = _make_flask_app()
    with app.app_context():
        from project import app_session
        from project.services.credit_risk import pd_rating_df as _pd_rating_df
        from project.db_models.calibration_models import Dataset
        from project.db_models.credit_models import CreditRiskRun
        from project.db_models.forecast_models import ForecastRun

        cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
        if not cr:
            logger.error(f"CreditRiskRun {cr_run_id} not found")
            return
        if cr.status == "failed":
            # Cancelled while queued — a worker picked it up after the fact.
            return

        workflow_run_id = cr.workflow_run_id
        dataset_id = cr.dataset_id
        financial_portfolio_dataset_id = cr.financial_portfolio_dataset_id
        forecast_inputs = {
            inp.slot: inp.forecast_run_uuid for inp in cr.forecast_inputs_rel
        }
        exposure = cr.exposure
        discount_rate = cr.discount_rate
        lifetime_horizon = cr.lifetime_horizon
        curve = cr.curve

        try:
            # 1. Mark running
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                r.status = "running"
                r.started_at = datetime.now(timezone.utc)
                s.add(r)
            if workflow_run_id:
                advance_workflow.delay(workflow_run_id)
            _cr_log(cr_run_id, "Analysis started")

            # 2. Load credit dataset from MinIO
            def _load_df_from_dataset(ds_id: int) -> tuple[str, pd.DataFrame]:
                """Download a dataset by PK and return (name, DataFrame)."""
                ds = Dataset.query.get(ds_id)
                if not ds or not ds.file_path:
                    raise ValueError(f"Dataset {ds_id} not found or has no file")
                name = ds.name
                file_bytes = storage.download_bytes(ds.file_path.split("/", 1)[-1])
                ext = ds.file_path.rsplit(".", 1)[-1].lower()
                buf = io.BytesIO(file_bytes)
                if ext == "csv":
                    return name, pd.read_csv(buf)
                elif ext == "xlsx":
                    return name, pd.read_excel(buf)
                elif ext == "parquet":
                    return name, pd.read_parquet(buf)
                raise ValueError(f"Unsupported file type: {ext}")

            credit_ds_name, credit_df = _load_df_from_dataset(dataset_id)
            _cr_log(cr_run_id, f"Loading credit portfolio: {credit_ds_name}")
            required_credit = {
                "client_id",
                "market_cap",
                "vol_equity",
                "risk_free_rate",
                "rating",
            }
            missing_credit = required_credit - set(credit_df.columns)
            if missing_credit:
                raise ValueError(
                    f"Credit dataset missing required columns: {missing_credit}"
                )

            # Optionally load financial portfolio and merge to get country/sector/subsector
            if financial_portfolio_dataset_id:
                fin_ds_name, fin_df = _load_df_from_dataset(
                    financial_portfolio_dataset_id
                )
                _cr_log(cr_run_id, f"Loading financial portfolio: {fin_ds_name}")
                required_fin = {"client_id", "country", "sector", "subsector"}
                missing_fin = required_fin - set(fin_df.columns)
                if missing_fin:
                    raise ValueError(
                        f"Financial portfolio dataset missing required columns: {missing_fin}"
                    )
                # One row per client for the metadata join (country/sector/subsector are static)
                fin_meta = fin_df[
                    ["client_id", "country", "sector", "subsector"]
                ].drop_duplicates(subset=["client_id"])
                # Only add columns from financial portfolio not already in credit portfolio
                new_fin_cols = ["client_id"] + [
                    c
                    for c in fin_meta.columns
                    if c != "client_id" and c not in credit_df.columns
                ]
                portfolio_df = credit_df.merge(
                    fin_meta[new_fin_cols], on="client_id", how="left"
                )
                _cr_log(
                    cr_run_id,
                    f"Merged {len(fin_meta)} financial portfolio clients into credit portfolio",
                    progress=2,
                )
            else:
                portfolio_df = credit_df

            n_clients = len(portfolio_df)
            _cr_log(cr_run_id, f"Loaded {n_clients} clients from dataset", progress=2)

            # 3. Build per-variable forecast indices from the 3 required forecast runs.
            #    idx_map[ctx][scenario][year] = predicted, where ctx is:
            #      - a segment_key (calibration was segmented — the forecast run scored
            #        every trained segment against the MEV-only dataset)
            #      - None (single portfolio-wide trajectory, non-segmented calibration)
            from project.core.credit_risk.forecast_lookup import (
                build_variable_index,
            )

            REQUIRED_INPUTS = ("total_assets", "short_term_debts", "long_term_debts")
            missing_inputs = [k for k in REQUIRED_INPUTS if not forecast_inputs.get(k)]
            if missing_inputs:
                raise ValueError(f"Missing required forecast inputs: {missing_inputs}")

            forecast_by_var: dict[
                str, dict[str | None, dict[str, dict[int, float]]]
            ] = {}
            # forecast_segmentation[key] = {
            #   "split_by": {sector: 'subsector'|'country'},
            #   "top_values": {sector: {trained split_value, ...}},  # includes "Others"
            #   "fallback": {sector: any segment_key for that sector},
            # }
            forecast_segmentation: dict[str, dict] = {}

            for key in REQUIRED_INPUTS:
                fr_run_uuid = forecast_inputs[key]
                fr = ForecastRun.query.filter_by(run_id=fr_run_uuid).first()
                if not fr or fr.status != "success":
                    raise ValueError(
                        f"Forecast run for '{key}' ({fr_run_uuid[:8]}…) not found or not successful"
                    )
                seg_info, idx_map = build_variable_index(fr)
                forecast_segmentation[key] = seg_info
                forecast_by_var[key] = idx_map

                ctx_desc = (
                    f"{len(idx_map)} segments"
                    if seg_info["split_by"]
                    else "portfolio-wide"
                )
                _cr_log(
                    cr_run_id,
                    f"Loaded '{key}' forecast from run {fr_run_uuid[:8]}… ({ctx_desc})",
                )

            # 4. Load PD ratings
            pd_rating_df = _pd_rating_df(curve)
            if pd_rating_df.empty:
                raise ValueError("No PD ratings found — run flask db upgrade first")
            _cr_log(
                cr_run_id,
                f"Loaded PD rating table ({len(pd_rating_df)} rows, curve={curve})",
                progress=5,
            )

            # 5. Process each client (KMV + ECL) and persist results.
            clients_list = portfolio_df.to_dict(orient="records")
            n_clients = len(clients_list)
            succeeded, failed_clients = _compute_credit_for_clients(
                cr_run_id,
                clients_list,
                forecast_segmentation,
                forecast_by_var,
                pd_rating_df,
                exposure,
                discount_rate,
                lifetime_horizon,
                progress_span=_CLIENT_COMPUTE_END,
            )

            # 6. Client risk computation done — the KMV+ECL results now exist, but the
            # run stays "running" through the finalization below so the workflow
            # doesn't complete (and the stepper stays out of "Complete") until the
            # analysis views are materialised. Progress sits at _CLIENT_COMPUTE_END.
            summary = (
                f"Client risk computation complete: {succeeded}/{n_clients} clients"
            )
            if failed_clients:
                summary += f" ({failed_clients} failed)"
            _cr_log(cr_run_id, summary, progress=_CLIENT_COMPUTE_END)

            # 7. Materialise the Heatmap / Financial Forecast level series so those
            # pages load from cheap indexed SELECTs instead of recomputing from
            # MinIO + pandas on every request. Best-effort: a failure here must not
            # fail the analysis run (the pages fall back to lazy on-demand compute).
            # Progress runs _CLIENT_COMPUTE_END → 100 across this phase.
            try:
                from project.services.credit_risk_analysis import (
                    analysis_portfolio_df as _analysis_portfolio_df,
                )
                from project.services.credit_risk_analysis import (
                    slot_forecast_runs as _slot_forecast_runs,
                )
                from project.core.credit_risk.analysis_series import (
                    materialize_analysis_series,
                )

                def _mat_progress(message: str, frac: float):
                    prog = _CLIENT_COMPUTE_END + round(
                        frac * (100 - _CLIENT_COMPUTE_END)
                    )
                    _cr_log(cr_run_id, message, progress=prog)

                _cr_log(
                    cr_run_id,
                    "Finalizing analysis views (heatmap & financial forecast)…",
                    progress=_CLIENT_COMPUTE_END,
                )
                with app_session():
                    cr_obj = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                    portfolio_df = _analysis_portfolio_df(cr_obj)
                    slots = _slot_forecast_runs(cr_obj)
                    n_series = materialize_analysis_series(
                        cr_obj, portfolio_df, slots, on_progress=_mat_progress
                    )
                _cr_log(cr_run_id, f"Materialised {n_series} analysis series rows")
            except Exception as mat_err:
                logger.error(
                    f"Analysis-series materialisation failed for {cr_run_id}: {mat_err}",
                    exc_info=True,
                )
                _cr_log(
                    cr_run_id,
                    f"Analysis series not materialised: {mat_err}",
                    level="warn",
                )

            # 8. Mark success (progress 100) and invalidate cached reads. Done only
            # after finalization so success ⇒ analysis views are ready.
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                r.status = "success"
                r.finished_at = datetime.now(timezone.utc)
                r.progress = 100
                s.add(r)

            # Results changed (initial run or rerun reusing this run_id) — drop the
            # cached results frame and transition matrices so reads recompute fresh.
            try:
                from project import cache

                cache.delete(f"cr_run_results:{cr_run_id}")
                cache.delete(f"cr_transitions:{cr_run_id}")
            except Exception:
                # Stale cache is self-healing (next read recomputes); log so a
                # persistently broken cache backend is still visible.
                logger.exception(
                    "Cache invalidation failed for credit run %s", cr_run_id
                )

            if workflow_run_id:
                advance_workflow.delay(workflow_run_id)

        except Exception as exc:
            logger.error(f"Credit risk run {cr_run_id} failed: {exc}", exc_info=True)
            _cr_log(cr_run_id, f"Analysis failed: {exc}", level="error")
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                if r:
                    r.status = "failed"
                    r.finished_at = datetime.now(timezone.utc)
                    r.error_message = format_failure(exc)
                    s.add(r)
            if workflow_run_id:
                advance_workflow.delay(workflow_run_id)
            raise


@celery_app.task(name="backfill_analysis_series")
def backfill_analysis_series(cr_run_id: str):
    """Materialise the Heatmap / Financial Forecast level series for a run that has
    none yet (a legacy run predating the feature, or one whose best-effort step at
    job completion failed).

    Dispatched from the analysis endpoints instead of computing inline in the web
    request — the portfolio load + per-client aggregation is a heavy pandas job that
    must never block an HTTP worker (or a 5s poll). Idempotent: rewrites the run's
    rows. The caller dedups dispatch with a short cache lock so concurrent pollers
    only enqueue this once.
    """
    from project import app_session
    from project.services.credit_risk_analysis import (
        analysis_portfolio_df as _analysis_portfolio_df,
    )
    from project.services.credit_risk_analysis import (
        slot_forecast_runs as _slot_forecast_runs,
    )
    from project.core.credit_risk.analysis_series import materialize_analysis_series
    from project.db_models.credit_models import CreditRiskRun

    try:
        with app_session():
            cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
            if not cr or cr.status != "success":
                return
            portfolio_df = _analysis_portfolio_df(cr)
            slots = _slot_forecast_runs(cr)
            n_series = materialize_analysis_series(
                cr,
                portfolio_df,
                slots,
                on_progress=lambda msg, frac: _cr_log(cr_run_id, msg),
            )
        _cr_log(cr_run_id, f"Backfilled {n_series} analysis series rows")
    except Exception as exc:
        logger.error(
            f"Analysis-series backfill failed for {cr_run_id}: {exc}", exc_info=True
        )
        _cr_log(cr_run_id, f"Analysis series backfill failed: {exc}", level="warn")
        raise
