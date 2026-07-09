import json
from datetime import datetime, timezone

import pandas as pd
from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.orm import selectinload

from project import app_session, cache, db
from project.api.auth.decorators import require_perm
from project.api.utils import paginate_logs
from project.core import table_query
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunLog,
    CalibrationRunSegment,
    Dataset,
    Forecast,
    ModelConfig,
)
from project.api.helpers import pagination_envelope
from project.db_models.forecast_models import ForecastRun
from project.logger import get_logger
from project.schemas.calibrations import CreateCalibrationRun
from project.services import calibrations as calibration_service
from project.services.run_guards import ensure_not_workflow_member
from project.workers.tasks import run_calibration, run_segment_calibration

from . import calibrations

logger = get_logger(__name__)


@calibrations.get("/")
@require_perm("calibration:read")
def list_runs():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    status_filter = request.args.get("status")

    q = (
        CalibrationRun.query.options(
            selectinload(CalibrationRun.model_config),
            selectinload(CalibrationRun.dataset),
        )
        .join(Dataset, CalibrationRun.dataset_id == Dataset.id)
        .join(ModelConfig, CalibrationRun.model_config_id == ModelConfig.id)
        .order_by(CalibrationRun.started_at.desc())
    )

    if status_filter:
        q = q.filter(CalibrationRun.status == status_filter)

    runs = q.paginate(page=page, per_page=per_page, error_out=False)
    result = []
    for r in runs.items:
        d = r.to_dict()
        d["config_name"] = r.model_config.name if r.model_config else None
        d["run_name"] = r.name or d["config_name"]
        d["dataset_name"] = r.dataset.name if r.dataset else None
        d["algorithm"] = r.model_config.algorithm if r.model_config else None
        d["model_family"] = r.model_config.family if r.model_config else None
        result.append(d)

    return jsonify(pagination_envelope(result, runs)), 200


@calibrations.post("/")
@require_perm("calibration:execute")
def create_run():
    payload = CreateCalibrationRun.model_validate(request.get_json(silent=True) or {})
    result = calibration_service.create_run(payload, get_jwt_identity())
    return jsonify(result), 202


@calibrations.get("/<run_id>")
@require_perm("calibration:read")
def get_run(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    d = run.to_dict()
    d["config_name"] = run.model_config.name if run.model_config else None
    d["run_name"] = run.name or d["config_name"]
    d["dataset_name"] = run.dataset.name if run.dataset else None
    d["algorithm"] = run.model_config.algorithm if run.model_config else None
    d["model_family"] = run.model_config.family if run.model_config else None
    # A segment re-run leaves this run at "success"; expose the in-flight count so
    # the job page can show a "Retraining" state and keep polling until it lands.
    d["retraining_segment_count"] = (
        CalibrationRunSegment.query.filter(
            CalibrationRunSegment.calibration_run_id == run.id,
            CalibrationRunSegment.status.in_(("queued", "running")),
        ).count()
        if run.seg_sectors_json is not None
        else 0
    )
    if run.workflow_run_id:
        from project.db_models.workflow_models import WorkflowRun

        wf = WorkflowRun.query.get(run.workflow_run_id)
        d["workflow_run_uuid"] = wf.run_id if wf else None
    return jsonify(d), 200


# The per-observation validation arrays are what make the segment metrics blobs
# huge. The segment LIST never needs them — the actual-vs-predicted scatter fetches
# them for the ONE selected segment via GET /<run_id>/diagnostics?segment_key=.
# `residuals`/`fitted` are kept: they're single arrays the aggregate residual
# histogram sums across segments, and dropping them would break that view.
_HEAVY_METRIC_KEYS = ("val_obs", "train_obs")


def _slim_metrics(m):
    """Drop the big per-observation arrays from a metrics dict, keeping the rest."""
    if not isinstance(m, dict):
        return m
    return {k: v for k, v in m.items() if k not in _HEAVY_METRIC_KEYS}


def _serialize_segment(s, algorithm, full):
    d = s.to_dict()
    d["algorithm"] = algorithm
    if not full:
        d["val_metrics"] = _slim_metrics(d.get("val_metrics"))
        d["train_metrics"] = _slim_metrics(d.get("train_metrics"))
    return d


@calibrations.get("/<run_id>/segments")
@require_perm("calibration:read")
def get_segments(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404

    # ?include=full|val_obs returns the heavy prediction arrays (back-compat); by
    # default the list is slim so it doesn't ship multi-MB val_obs per segment.
    full = request.args.get("include") in ("full", "val_obs")
    # ?sectors=a,b restricts to specific sectors so the UI only loads the sector(s)
    # the user picked instead of every segment in the run.
    sectors_arg = request.args.get("sectors")
    sectors = (
        [s.strip() for s in sectors_arg.split(",") if s.strip()]
        if sectors_arg
        else None
    )

    q = CalibrationRunSegment.query.filter_by(calibration_run_id=run.id)
    if sectors:
        q = q.filter(CalibrationRunSegment.sector.in_(sectors))
    segs = q.order_by(
        CalibrationRunSegment.sector, CalibrationRunSegment.split_value
    ).all()

    config_ids = {s.model_config_id for s in segs if s.model_config_id}
    configs = (
        {
            c.id: c.algorithm
            for c in ModelConfig.query.filter(ModelConfig.id.in_(config_ids))
        }
        if config_ids
        else {}
    )
    result = [_serialize_segment(s, configs.get(s.model_config_id), full) for s in segs]
    # Defaults the per-segment customize panel offers as its baseline: the run's
    # configuration and feature set. A segment override may pick a different saved
    # config and/or a subset of these features.
    default_feature_cols = json.loads(run.feature_cols_json or "[]")
    return jsonify(
        {
            "segments": result,
            "default_model_config_id": run.model_config_id,
            "default_feature_cols": default_feature_cols,
            "feature_options": default_feature_cols,
        }
    ), 200


@calibrations.get("/<run_id>/segments/sectors")
@require_perm("calibration:read")
def get_segment_sectors(run_id):
    """Distinct sector list for a run's segments — backs the Sector filter so it can
    populate without pulling the (slim but still per-segment) full segment list."""
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    rows = (
        db.session.query(CalibrationRunSegment.sector)
        .filter(CalibrationRunSegment.calibration_run_id == run.id)
        .distinct()
        .order_by(CalibrationRunSegment.sector)
        .all()
    )
    return jsonify({"sectors": [r[0] for r in rows]}), 200


@calibrations.post("/<run_id>/segments/<segment_key>/recalibrate")
@require_perm("calibration:execute")
def recalibrate_segment(run_id, segment_key):
    """Re-fit a single segment of a segmented run with an optional configuration,
    feature-column and/or hyperparameter override. Only this segment is retrained
    — the parent run and every other segment are untouched."""
    body = request.get_json(silent=True) or {}
    hyperparams = body.get("hyperparams")
    if hyperparams is not None and not isinstance(hyperparams, dict):
        return jsonify({"error": "hyperparams must be an object"}), 400

    model_config_id = body.get("model_config_id")
    if model_config_id is not None:
        try:
            model_config_id = int(model_config_id)
        except (TypeError, ValueError):
            return jsonify({"error": "model_config_id must be an integer"}), 400

    feature_cols = body.get("feature_cols")
    if feature_cols is not None:
        if not isinstance(feature_cols, list) or not all(
            isinstance(c, str) for c in feature_cols
        ):
            return jsonify({"error": "feature_cols must be a list of strings"}), 400

    with app_session() as s:
        run = CalibrationRun.query.filter_by(run_id=run_id).first()
        if not run:
            return jsonify({"error": "Not found"}), 404
        if run.status != "success":
            return jsonify(
                {"error": "Segments can only be re-run on a completed run"}
            ), 409
        seg = CalibrationRunSegment.query.filter_by(
            calibration_run_id=run.id, segment_key=segment_key
        ).first()
        if not seg:
            return jsonify({"error": f"Segment '{segment_key}' not found"}), 404
        if seg.status in ("queued", "running"):
            return jsonify({"error": "Segment is already re-training"}), 409

        if model_config_id is not None:
            cfg = ModelConfig.query.get(model_config_id)
            if not cfg:
                return jsonify(
                    {"error": f"ModelConfig {model_config_id} not found"}
                ), 400
            seg.model_config_id = model_config_id

        seg.status = "queued"
        seg.error_message = None
        seg.hyperparams_json = json.dumps(hyperparams) if hyperparams else None
        # An explicit empty list is a meaningful "no features" choice; only a
        # missing key falls back to the run defaults (NULL).
        seg.feature_cols_json = (
            json.dumps(feature_cols) if feature_cols is not None else None
        )
        s.add(seg)
        s.flush()
        result = seg.to_dict()
        cfg = (
            ModelConfig.query.get(seg.model_config_id) if seg.model_config_id else None
        )
        result["algorithm"] = cfg.algorithm if cfg else None

    # The segment's cached backtest predictions are now stale — its model is being
    # re-fit. Drop them so the next read rebuilds from the fresh val_obs.
    _invalidate_segment_predictions(run_id, segment_key)
    run_segment_calibration.delay(run_id, segment_key)
    return jsonify(result), 202


@calibrations.get("/<run_id>/diagnostics")
@require_perm("calibration:read")
def get_diagnostics(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    if run.status != "success":
        return jsonify(
            {"error": f"Run is {run.status}, diagnostics not available"}
        ), 409

    segment_key = request.args.get("segment_key")
    if segment_key:
        seg = CalibrationRunSegment.query.filter_by(
            calibration_run_id=run.id, segment_key=segment_key
        ).first()
        if not seg:
            return jsonify({"error": f"Segment '{segment_key}' not found"}), 404
        if seg.status != "success":
            return jsonify({"error": f"Segment is {seg.status}"}), 409
        metrics = json.loads(seg.val_metrics_json or "{}")
        return jsonify(
            {
                "run_id": run_id,
                "segment_key": segment_key,
                "sector": seg.sector,
                "split_value": seg.split_value,
                "config_name": run.model_config.name if run.model_config else None,
                "algorithm": run.model_config.algorithm if run.model_config else None,
                "metrics": metrics,
            }
        ), 200

    metrics = json.loads(run.val_metrics_json or "{}")
    return jsonify(
        {
            "run_id": run_id,
            "config_name": run.model_config.name if run.model_config else None,
            "algorithm": run.model_config.algorithm if run.model_config else None,
            "metrics": metrics,
        }
    ), 200


@calibrations.get("/<run_id>/forecast")
@require_perm("calibration:read")
def get_forecast(run_id):
    from project.workers.tasks import _load_forecast_data

    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    forecasts = (
        Forecast.query.filter_by(calibration_run_id=run.id)
        .order_by(Forecast.created_at)
        .all()
    )
    result = []
    for f in forecasts:
        d = f.to_dict()
        d["forecast_json"] = _load_forecast_data(f)
        result.append(d)
    return jsonify(result), 200


def _predictions_df(
    actual: list, predicted: list, meta: dict, model_family: str | None
):
    """Build a predictions DataFrame (actual/predicted/meta columns, plus a
    derived residual or pred_class+correct column) from parallel arrays."""
    records = {"actual": actual, "predicted": predicted, **meta}
    df = pd.DataFrame(records)
    if df.empty:
        return df
    df = df[df["actual"].notna() & df["predicted"].notna()].reset_index(drop=True)
    if model_family == "classification":
        df["pred_class"] = (df["predicted"] >= 0.5).astype(int)
        df["correct"] = df["actual"].round().astype(int) == df["pred_class"]
    else:
        df["residual"] = df["actual"] - df["predicted"]
    return df


def _run_predictions_df(run: CalibrationRun) -> pd.DataFrame:
    """Predictions for a non-segmented run, from Forecast/ForecastResult rows.

    Cached per immutable run_id for successful, non-segmented runs (their results
    never change), so paging/sorting/filtering the backtest table doesn't reload and
    re-parse every ForecastResult row on each request. Segmented runs are excluded —
    a segment re-run can change their downstream forecast."""
    from project.workers.tasks import _load_forecast_data

    cacheable = run.status == "success" and not run.is_segmented
    cache_key = f"calib_run_preds:{run.run_id}"
    if cacheable:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    forecast = (
        Forecast.query.filter_by(calibration_run_id=run.id)
        .order_by(Forecast.created_at)
        .first()
    )
    if not forecast:
        return pd.DataFrame()
    data = _load_forecast_data(forecast)
    family = run.model_config.family if run.model_config else None
    df = _predictions_df(
        data.get("actual", []), data.get("predicted", []), data.get("meta", {}), family
    )
    if cacheable:
        cache.set(cache_key, df, timeout=3600)
    return df


def _segment_predictions_df(
    run: CalibrationRun, segment_key: str
) -> pd.DataFrame | None:
    """Predictions for one segment, from CalibrationRunSegment.val_metrics_json's
    val_obs. Returns None if the segment doesn't exist. Older runs (predating
    val_obs) fall back to reconstructing actual/predicted from fitted+residuals
    (regression only — mirrors SegmentBacktestTab.vue's client-side fallback)."""
    seg = CalibrationRunSegment.query.filter_by(
        calibration_run_id=run.id, segment_key=segment_key
    ).first()
    if not seg:
        return None

    # Cache per (run, segment) while the segment is successful — its val_obs only
    # changes when the segment is re-fit (which deletes this key, see
    # _invalidate_segment_predictions). Avoids re-parsing the whole val_obs blob on
    # every page/sort/filter of the backtest table.
    cacheable = seg.status == "success"
    cache_key = _segment_predictions_cache_key(run.run_id, segment_key)
    if cacheable:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    diag = json.loads(seg.val_metrics_json or "{}")
    family = run.model_config.family if run.model_config else None

    df = _build_segment_predictions_df(diag, family)
    if cacheable:
        cache.set(cache_key, df, timeout=3600)
    return df


def _segment_predictions_cache_key(run_id: str, segment_key: str) -> str:
    return f"calib_seg_preds:{run_id}:{segment_key}"


def _invalidate_segment_predictions(run_id: str, segment_key: str):
    """Drop the cached backtest DataFrame for a segment (call when it is re-fit)."""
    cache.delete(_segment_predictions_cache_key(run_id, segment_key))


def _build_segment_predictions_df(diag: dict, family: str | None) -> pd.DataFrame:
    val_obs = diag.get("val_obs")
    if val_obs:
        return _predictions_df(
            val_obs.get("actual", []),
            val_obs.get("predicted", []),
            val_obs.get("meta", {}),
            family,
        )

    fitted = diag.get("fitted")
    if fitted and family != "classification":
        residuals = diag.get("residuals", [])
        actual = [
            f + (residuals[i] if i < len(residuals) else 0)
            for i, f in enumerate(fitted)
        ]
        return _predictions_df(actual, fitted, {}, family)

    return pd.DataFrame()


def _predictions_page_response(df: pd.DataFrame):
    page, total = table_query.query_page(
        df,
        page=int(request.args.get("page", 0)),
        page_size=int(request.args.get("page_size", 50)),
        sort_column=request.args.get("sort_column"),
        sort_order=request.args.get("sort_order"),
        filters=table_query.parse_filters(request.args.get("filters")),
    )
    rows = page.where(pd.notnull(page), None).to_dict(orient="records")
    return jsonify({"rows": rows, "total": total, "columns": list(df.columns)}), 200


def _predictions_distinct_response(df: pd.DataFrame):
    column = request.args.get("column", "")
    if not column:
        return jsonify({"values": [], "truncated": False}), 200
    return jsonify(table_query.distinct_values(df, column)), 200


@calibrations.get("/<run_id>/backtest/predictions")
@require_perm("calibration:read")
def get_backtest_predictions(run_id):
    """Paginated per-observation backtest predictions for a non-segmented run
    (backs ForecastTab.vue)."""
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    return _predictions_page_response(_run_predictions_df(run))


@calibrations.get("/<run_id>/backtest/predictions/distinct")
@require_perm("calibration:read")
def get_backtest_predictions_distinct(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    return _predictions_distinct_response(_run_predictions_df(run))


@calibrations.get("/<run_id>/segments/<segment_key>/backtest/predictions")
@require_perm("calibration:read")
def get_segment_backtest_predictions(run_id, segment_key):
    """Paginated per-observation validation predictions for one segment
    (backs SegmentBacktestTab.vue)."""
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    df = _segment_predictions_df(run, segment_key)
    if df is None:
        return jsonify({"error": f"Segment '{segment_key}' not found"}), 404
    return _predictions_page_response(df)


@calibrations.get("/<run_id>/segments/<segment_key>/backtest/predictions/distinct")
@require_perm("calibration:read")
def get_segment_backtest_predictions_distinct(run_id, segment_key):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    df = _segment_predictions_df(run, segment_key)
    if df is None:
        return jsonify({"error": f"Segment '{segment_key}' not found"}), 404
    return _predictions_distinct_response(df)


@calibrations.post("/<run_id>/cancel")
@require_perm("calibration:write")
def cancel_run(run_id):
    with app_session() as s:
        r = CalibrationRun.query.filter_by(run_id=run_id).first()
        if not r:
            return jsonify({"error": "Not found"}), 404
        if r.status not in ("queued", "running"):
            return jsonify(
                {"error": f"Cannot cancel a run with status {r.status}"}
            ), 409
        r.status = "failed"
        r.finished_at = datetime.now(timezone.utc)
        r.error_message = "Cancelled by user"
        workflow_run_id = r.workflow_run_id
        s.add(r)
        s.flush()
        result = r.to_dict()
    if workflow_run_id:
        from project.workers.tasks import advance_workflow

        advance_workflow.delay(workflow_run_id)
    return jsonify(result), 200


@calibrations.get("/<run_id>/logs")
@require_perm("calibration:read")
def get_logs(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    logs = paginate_logs(
        CalibrationRunLog.query.filter_by(run_id=run_id), CalibrationRunLog.id
    )
    return jsonify([log.to_dict() for log in logs]), 200


@calibrations.get("/<run_id>/refs")
@require_perm("calibration:read")
def get_refs(run_id):
    r = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not r:
        return jsonify({"error": "Not found"}), 404
    forecast_refs = ForecastRun.query.filter_by(calibration_run_id=r.id).all()
    return jsonify(
        {
            "forecast_runs": [
                {"run_id": fr.run_id, "name": fr.name, "status": fr.status}
                for fr in forecast_refs
            ]
        }
    ), 200


def _check_forecast_references(cal_run_id: int):
    """Return a 409 response if forecast runs reference this calibration run, else None."""
    refs = ForecastRun.query.filter_by(calibration_run_id=cal_run_id).all()
    if refs:
        n = len(refs)
        return (
            jsonify(
                {
                    "error": f"This calibration run is used by {n} forecast job(s). "
                    "Delete those forecast jobs first, then retry."
                }
            ),
            409,
        )
    return None, None


@calibrations.delete("/<run_id>")
@require_perm("calibration:write")
def delete_run(run_id):
    r = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not r:
        return jsonify({"error": "Not found"}), 404
    if r.status in ("queued", "running"):
        return jsonify({"error": "Cannot delete an active run — cancel it first"}), 409
    ensure_not_workflow_member(r)
    err, code = _check_forecast_references(r.id)
    if err:
        return err, code
    with app_session() as s:
        s.delete(CalibrationRun.query.get(r.id))
    return "", 204


@calibrations.post("/bulk-delete")
@require_perm("calibration:write")
def bulk_delete_runs():
    run_ids = (request.get_json(silent=True) or {}).get("run_ids", [])
    if not run_ids:
        return jsonify({"error": "run_ids is required"}), 400

    deleted, skipped = [], []
    for rid in run_ids:
        run = CalibrationRun.query.filter_by(run_id=rid).first()
        if not run:
            continue
        if run.status in ("queued", "running"):
            skipped.append(rid)
            continue
        if run.workflow_run_id:
            skipped.append(rid)
            continue
        err, _ = _check_forecast_references(run.id)
        if err:
            skipped.append(rid)
            continue
        with app_session() as s:
            s.delete(CalibrationRun.query.get(run.id))
        deleted.append(rid)

    return jsonify(
        {"deleted": len(deleted), "deleted_ids": deleted, "skipped": len(skipped)}
    ), 200


@calibrations.post("/<run_id>/recalibrate")
@require_perm("calibration:execute")
def recalibrate(run_id):
    with app_session() as s:
        r = CalibrationRun.query.filter_by(run_id=run_id).first()
        if not r:
            return jsonify({"error": "Not found"}), 404
        if r.status in ("queued", "running"):
            return jsonify({"error": "Run is already active"}), 409
        ensure_not_workflow_member(r)

        r.status = "queued"
        r.triggered_by = get_jwt_identity()
        r.started_at = None
        r.finished_at = None
        r.artifact_path = None
        r.error_message = None
        r.val_metrics_json = None
        r.train_metrics_json = None
        r.best_params_json = None
        r.progress = 0
        r.progress_message = None
        s.add(r)
        CalibrationRunLog.query.filter_by(run_id=run_id).delete()
        for f in Forecast.query.filter_by(calibration_run_id=r.id).all():
            s.delete(f)
        s.flush()
        result = r.to_dict()

    run_calibration.delay(run_id)
    return jsonify(result), 202
