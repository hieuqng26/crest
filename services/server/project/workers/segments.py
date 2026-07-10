from datetime import datetime, timezone


from project.workers import celery_app
from project.workers.common import (
    REQUIRED_SLOTS,
    SLOT_BY_TARGET,
    _cr_log,
    _load_df_by_dataset_id,
    _make_flask_app,
    _split_segment_key,
    format_failure,
)


from project.workers.credit import (
    _build_credit_portfolio_df,
    _compute_credit_for_clients,
)
from project.workers.forecast import recompute_forecast_run_segment


from project.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, name="recompute_segment_downstream")
def recompute_segment_downstream(self, run_id: str, segment_key: str):
    """After a single segment is re-fit, recompute its downstream forecast + credit
    results IN PLACE — for that segment only — so the workflow's Forecast and Credit
    tabs stop showing numbers produced by the old segment model.

    Never calls advance_workflow: that machine is one-shot and would spawn duplicate
    runs. This is an out-of-band correction that flips the affected ForecastRun(s) +
    CreditRiskRun to running while recomputing, then back to success. Each per-segment
    delete+insert is one atomic transaction, gated behind status='running', so the
    frontend never renders a success run missing a segment's rows.
    """
    from project.workers.credit import (
        backfill_analysis_series,
    )  # deferred: avoids import cycle

    app = _make_flask_app()
    with app.app_context():
        from project import app_session
        from project.services.credit_risk import pd_rating_df as _pd_rating_df
        from project.core.credit_risk.forecast_lookup import build_variable_index
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunSegment,
        )
        from project.db_models.credit_models import CreditRiskResult, CreditRiskRun
        from project.db_models.forecast_models import ForecastRun, ForecastRunLog

        # Sector/segment tags for the unified workflow log lines below.
        seg_sector, seg_split = _split_segment_key(segment_key)

        cal = CalibrationRun.query.filter_by(run_id=run_id).first()
        if not cal:
            logger.error(f"recompute_segment_downstream: cal run {run_id} not found")
            return
        if cal.seg_sectors_json is None:
            # Non-segmented run has no per-segment downstream to recompute.
            return
        cal_id = cal.id
        workflow_run_id = cal.workflow_run_id
        target_col = cal.target_col

        # Affected forecast runs: every forecast run built from this calibration.
        # (Segmented cals produce one forecast run per target, each scoring all
        # segments; a failed/incomplete run is left alone.)
        affected = ForecastRun.query.filter_by(
            calibration_run_id=cal_id, status="success"
        ).all()
        if not affected:
            return

        seg = CalibrationRunSegment.query.filter_by(
            calibration_run_id=cal_id, segment_key=segment_key, status="success"
        ).first()
        if not seg:
            logger.error(
                f"recompute_segment_downstream: segment '{segment_key}' not found/"
                f"successful for run {run_id}"
            )
            return
        seg_artifact_path = seg.artifact_path
        affected_ids = [(fr.id, fr.run_id, fr.dataset_id) for fr in affected]

        # ── Forecast stage: re-score this segment into each affected run ──────────
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for fr_id, fr_run_uuid, fr_dataset_id in affected_ids:
            # Txn 1: gate the tab OFF before any delete.
            with app_session() as s:
                fr = ForecastRun.query.get(fr_id)
                fr.status = "running"
                fr.progress = 0
                s.add(fr)
                s.add(
                    ForecastRunLog(
                        run_id=fr_run_uuid,
                        t=now,
                        level="info",
                        message=f"Recomputing segment '{segment_key}'…",
                        sector=seg_sector,
                        segment=seg_split,
                    )
                )
            try:
                df = _load_df_by_dataset_id(fr_dataset_id)
                # Txn 2: atomic delete-this-segment + re-score + insert.
                with app_session() as s:
                    fr = ForecastRun.query.get(fr_id)
                    recompute_forecast_run_segment(
                        s, fr, df, seg_artifact_path, segment_key
                    )
                # Txn 3: back to success.
                with app_session() as s:
                    fr = ForecastRun.query.get(fr_id)
                    fr.status = "success"
                    fr.progress = 100
                    fr.finished_at = datetime.now(timezone.utc)
                    s.add(fr)
            except Exception as exc:
                logger.error(
                    f"Segment forecast recompute failed for {fr_run_uuid}: {exc}",
                    exc_info=True,
                )
                with app_session() as s:
                    fr = ForecastRun.query.get(fr_id)
                    fr.status = "failed"
                    fr.finished_at = datetime.now(timezone.utc)
                    fr.error_message = (
                        f"Segment '{segment_key}' recompute failed:\n"
                        f"{format_failure(exc)}"
                    )
                    s.add(fr)
                    s.add(
                        ForecastRunLog(
                            run_id=fr_run_uuid,
                            t=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            level="error",
                            message=f"Segment '{segment_key}' recompute failed: {exc}",
                            sector=seg_sector,
                            segment=seg_split,
                        )
                    )
                # Credit needs all forecast inputs current — abort before it.
                raise

        # The re-scored forecast(s) feed the Heatmap / Financial Forecast level
        # series and the cached forecast index. Invalidate that index cache and, if
        # this workflow has a credit run, re-materialise the series so those pages
        # reflect the re-fit segment instead of stale pre-retrain numbers. Done here
        # (after the forecast stage, before the credit early-returns) because the
        # forecast change alone can move the Heatmap even when credit is unaffected.
        try:
            from project import cache

            for _, fr_run_uuid, _ in affected_ids:
                cache.delete(f"cr_var_index:{fr_run_uuid}")
            if workflow_run_id:
                cr_for_series = CreditRiskRun.query.filter_by(
                    workflow_run_id=workflow_run_id
                ).first()
                if cr_for_series and cr_for_series.status == "success":
                    backfill_analysis_series.delay(cr_for_series.run_id)
        except Exception:
            logger.warning(
                "post-recompute analysis-series refresh dispatch failed", exc_info=True
            )

        # ── Credit stage: recompute only this segment's clients ──────────────────
        # Only when the retrained variable actually feeds KMV (revenue/cogs don't).
        if SLOT_BY_TARGET.get(target_col) not in REQUIRED_SLOTS:
            return
        if not workflow_run_id:
            return
        cr = CreditRiskRun.query.filter_by(workflow_run_id=workflow_run_id).first()
        if not cr or cr.status != "success":
            return

        cr_run_id = cr.run_id
        cr_dataset_id = cr.dataset_id
        cr_financial_id = cr.financial_portfolio_dataset_id
        exposure = cr.exposure
        discount_rate = cr.discount_rate
        lifetime_horizon = cr.lifetime_horizon
        curve = cr.curve
        forecast_inputs = {
            inp.slot: inp.forecast_run_uuid for inp in cr.forecast_inputs_rel
        }

        # Membership is stable (re-fitting a model doesn't change routing), so read
        # the affected clients straight off the persisted segment_key column.
        client_ids = {
            r.client_id
            for r in CreditRiskResult.query.filter_by(
                run_id=cr_run_id, segment_key=segment_key
            ).all()
        }
        if not client_ids:
            # Nothing routes to this segment (or rows predate the column) — don't
            # flip a good run to running to do nothing.
            _cr_log(
                cr_run_id,
                f"Segment '{segment_key}' recompute: no matching credit clients — skipped",
                sector=seg_sector,
                segment=seg_split,
            )
            return

        # Txn A: gate credit tabs OFF.
        with app_session() as s:
            r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
            r.status = "running"
            r.progress = 0
            r.started_at = datetime.now(timezone.utc)
            s.add(r)
        _cr_log(
            cr_run_id,
            f"Recomputing credit for segment '{segment_key}' ({len(client_ids)} clients)…",
            sector=seg_sector,
            segment=seg_split,
        )

        try:
            # Rebuild forecast indices from the (now-updated) required forecast runs.
            REQUIRED_INPUTS = ("total_assets", "short_term_debts", "long_term_debts")
            missing_inputs = [k for k in REQUIRED_INPUTS if not forecast_inputs.get(k)]
            if missing_inputs:
                raise ValueError(f"Missing required forecast inputs: {missing_inputs}")
            forecast_by_var: dict = {}
            forecast_segmentation: dict = {}
            for key in REQUIRED_INPUTS:
                fr = ForecastRun.query.filter_by(run_id=forecast_inputs[key]).first()
                if not fr or fr.status != "success":
                    raise ValueError(
                        f"Forecast run for '{key}' not found or not successful"
                    )
                seg_info, idx_map = build_variable_index(fr)
                forecast_segmentation[key] = seg_info
                forecast_by_var[key] = idx_map

            pd_rating_df = _pd_rating_df(curve)
            if pd_rating_df.empty:
                raise ValueError("No PD ratings found — run flask db upgrade first")

            portfolio_df = _build_credit_portfolio_df(cr_dataset_id, cr_financial_id)
            subset_df = portfolio_df[
                portfolio_df["client_id"].astype(str).isin(client_ids)
            ]

            # Txn B: atomic delete-this-segment + recompute (one flush for the subset).
            with app_session() as s:
                CreditRiskResult.query.filter_by(
                    run_id=cr_run_id, segment_key=segment_key
                ).delete(synchronize_session=False)
            _compute_credit_for_clients(
                cr_run_id,
                subset_df.to_dict(orient="records"),
                forecast_segmentation,
                forecast_by_var,
                pd_rating_df,
                exposure,
                discount_rate,
                lifetime_horizon,
                flush_every=max(1, len(subset_df)),
            )

            # Txn C: back to success + invalidate the cached results df.
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                r.status = "success"
                r.progress = 100
                r.finished_at = datetime.now(timezone.utc)
                s.add(r)
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
            _cr_log(
                cr_run_id,
                f"Segment '{segment_key}' credit recompute complete",
                progress=100,
                sector=seg_sector,
                segment=seg_split,
            )
        except Exception as exc:
            logger.error(
                f"Segment credit recompute failed for {cr_run_id}: {exc}",
                exc_info=True,
            )
            _cr_log(
                cr_run_id,
                f"Segment recompute failed: {exc}",
                level="error",
                sector=seg_sector,
                segment=seg_split,
            )
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                if r:
                    r.status = "failed"
                    r.finished_at = datetime.now(timezone.utc)
                    r.error_message = (
                        f"Segment '{segment_key}' recompute failed:\n"
                        f"{format_failure(exc)}"
                    )
                    s.add(r)
            raise


# Maps a workflow target_col to the slot name CreditRiskForecastInput/
# run_credit_analysis expects — the two use different vocabularies for the
# same three variables.
