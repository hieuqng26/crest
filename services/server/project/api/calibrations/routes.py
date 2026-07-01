import json
import math
import uuid
from datetime import datetime, timezone

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from project import app_session
from project.api.auth.decorators import require_perm
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunLog,
    CalibrationRunSegment,
    Dataset,
    Forecast,
    ModelConfig,
)
from project.db_models.forecast_models import ForecastRun
from project.logger import get_logger
from project.workers.tasks import run_calibration

from . import calibrations

logger = get_logger(__name__)


def _expand_param_values(defn: dict) -> list:
    """Expand a frontend param-grid definition into a flat list of candidate values."""
    kind = defn.get("kind", "list")
    if kind == "list":
        raw = str(defn.get("values", ""))
        parts = [s.strip() for s in raw.split(",") if s.strip()]
        result = []
        for p in parts:
            try:
                result.append(int(p))
            except ValueError:
                try:
                    result.append(float(p))
                except ValueError:
                    if p.lower() == "true":
                        result.append(True)
                    elif p.lower() == "false":
                        result.append(False)
                    else:
                        result.append(p)
        return result
    lo = float(defn.get("min", 0))
    hi = float(defn.get("max", 1))
    n = max(2, min(50, int(defn.get("steps", 5))))
    if lo == hi or n < 2:
        return [lo]
    if kind == "logspace":
        if lo <= 0 or hi <= 0:
            return []
        a, b = math.log10(lo), math.log10(hi)
        return [round(10 ** (a + (b - a) * i / (n - 1)), 10) for i in range(n)]
    return [round(lo + (hi - lo) * i / (n - 1), 10) for i in range(n)]


@calibrations.get("/")
@require_perm("calibration:read")
def list_runs():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    status_filter = request.args.get("status")

    q = (
        CalibrationRun.query.join(Dataset, CalibrationRun.dataset_id == Dataset.id)
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
        d["dataset_name"] = r.dataset.name if r.dataset else None
        d["algorithm"] = r.model_config.algorithm if r.model_config else None
        d["model_family"] = r.model_config.family if r.model_config else None
        result.append(d)

    return jsonify(
        {"items": result, "total": runs.total, "page": page, "pages": runs.pages}
    ), 200


@calibrations.post("/")
@require_perm("calibration:execute")
def create_run():
    body = request.get_json(silent=True) or {}
    dataset_id = body.get("dataset_id")
    if not dataset_id:
        return jsonify({"error": "Missing: dataset_id"}), 400

    model_config_id = body.get("model_config_id")
    if not model_config_id:
        return jsonify({"error": "Missing: model_config_id"}), 400

    ds = Dataset.query.get(int(dataset_id))
    cfg = ModelConfig.query.get(int(model_config_id))
    if not ds:
        return jsonify({"error": "Dataset not found"}), 404
    if not cfg:
        return jsonify({"error": "ModelConfig not found"}), 404

    seg = body.get("segmentation") or None
    seg_sectors_json = None
    seg_split_by = None
    seg_max_segments = None
    seg_sector_overrides_json = None
    if seg:
        sectors = seg.get("sectors") or []
        split_by = seg.get("split_by") or ""
        max_segs = seg.get("max_segments")
        if not sectors or not isinstance(sectors, list):
            return jsonify(
                {"error": "segmentation.sectors must be a non-empty list"}
            ), 400
        if split_by not in ("subsector", "country"):
            return jsonify(
                {"error": "segmentation.split_by must be 'subsector' or 'country'"}
            ), 400
        if not isinstance(max_segs, int) or not (2 <= max_segs <= 20):
            return jsonify(
                {"error": "segmentation.max_segments must be an integer 2–20"}
            ), 400
        seg_sectors_json = json.dumps(sectors)
        seg_split_by = split_by
        seg_max_segments = max_segs

        sector_overrides = seg.get("sector_overrides") or {}
        if sector_overrides:
            if not isinstance(sector_overrides, dict):
                return jsonify(
                    {"error": "segmentation.sector_overrides must be an object"}
                ), 400
            for sector_name, override in sector_overrides.items():
                if sector_name not in sectors:
                    return jsonify(
                        {
                            "error": f"segmentation.sector_overrides has an entry "
                            f"for '{sector_name}', which is not in "
                            f"segmentation.sectors"
                        }
                    ), 400
                if not isinstance(override, dict):
                    return jsonify(
                        {
                            "error": f"segmentation.sector_overrides['{sector_name}'] "
                            f"must be an object"
                        }
                    ), 400
                if "split_by" in override and override["split_by"] not in (
                    "subsector",
                    "country",
                ):
                    return jsonify(
                        {
                            "error": f"segmentation.sector_overrides['{sector_name}']"
                            f".split_by must be 'subsector' or 'country'"
                        }
                    ), 400
                if "max_segments" in override and (
                    not isinstance(override["max_segments"], int)
                    or not (2 <= override["max_segments"] <= 20)
                ):
                    return jsonify(
                        {
                            "error": f"segmentation.sector_overrides['{sector_name}']"
                            f".max_segments must be an integer 2–20"
                        }
                    ), 400
                if "model_config_id" in override:
                    model_cfg_id = override["model_config_id"]
                    if not isinstance(model_cfg_id, int):
                        return jsonify(
                            {
                                "error": f"segmentation.sector_overrides['{sector_name}']"
                                f".model_config_id must be an integer"
                            }
                        ), 400
                    override_cfg = ModelConfig.query.get(model_cfg_id)
                    if not override_cfg:
                        return jsonify(
                            {
                                "error": f"segmentation.sector_overrides"
                                f"['{sector_name}'].model_config_id "
                                f"{model_cfg_id} not found"
                            }
                        ), 400
                if "feature_cols" in override and not isinstance(
                    override["feature_cols"], list
                ):
                    return jsonify(
                        {
                            "error": f"segmentation.sector_overrides['{sector_name}']"
                            f".feature_cols must be a list"
                        }
                    ), 400
            seg_sector_overrides_json = json.dumps(sector_overrides)

    target_col = body.get("target_col") or None
    feature_cols = body.get("feature_cols") or []

    # Build resolved CV search config from model config's saved search settings
    search_config_json = None
    raw_search = json.loads(cfg.search_config_json or "null")
    if raw_search and raw_search.get("mode", "none") != "none":
        param_grid = {}
        for param_name, defn in (raw_search.get("paramGrid") or {}).items():
            if not defn or not defn.get("enabled"):
                continue
            values = _expand_param_values(defn)
            if values:
                param_grid[param_name] = values
        if param_grid:
            search_config_json = json.dumps(
                {
                    "type": raw_search.get("mode", "grid"),
                    "param_grid": param_grid,
                    "cv": int(raw_search.get("folds", 5)),
                    "scoring": raw_search.get("scoring", "roc_auc"),
                    "n_iter": int(raw_search.get("nIter", 20)),
                }
            )

    run_id = str(uuid.uuid4())
    with app_session() as session:
        run = CalibrationRun(
            run_id=run_id,
            dataset_id=ds.id,
            model_config_id=cfg.id,
            status="queued",
            triggered_by=get_jwt_identity(),
            search_config_json=search_config_json,
            train_split=cfg.train_split if cfg.train_split is not None else 0.8,
            scaler=cfg.scaler,
            target_col=target_col,
            feature_cols_json=json.dumps(feature_cols),
            seg_sectors_json=seg_sectors_json,
            seg_split_by=seg_split_by,
            seg_max_segments=seg_max_segments,
            seg_sector_overrides_json=seg_sector_overrides_json,
        )
        session.add(run)
        session.flush()
        result = run.to_dict()

    run_calibration.delay(run_id)
    return jsonify(result), 202


@calibrations.get("/<run_id>")
@require_perm("calibration:read")
def get_run(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    d = run.to_dict()
    d["config_name"] = run.model_config.name if run.model_config else None
    d["dataset_name"] = run.dataset.name if run.dataset else None
    d["algorithm"] = run.model_config.algorithm if run.model_config else None
    d["model_family"] = run.model_config.family if run.model_config else None
    return jsonify(d), 200


@calibrations.get("/<run_id>/segments")
@require_perm("calibration:read")
def get_segments(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    segs = (
        CalibrationRunSegment.query.filter_by(calibration_run_id=run.id)
        .order_by(CalibrationRunSegment.sector, CalibrationRunSegment.split_value)
        .all()
    )
    return jsonify({"segments": [s.to_dict() for s in segs]}), 200


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
        s.add(r)
        s.flush()
        result = r.to_dict()
    return jsonify(result), 200


@calibrations.get("/<run_id>/logs")
@require_perm("calibration:read")
def get_logs(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    logs = (
        CalibrationRunLog.query.filter_by(run_id=run_id)
        .order_by(CalibrationRunLog.logged_at)
        .all()
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
