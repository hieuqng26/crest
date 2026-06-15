import json
import uuid
from datetime import datetime, timezone

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from project import app_session
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunLog,
    Dataset,
    Forecast,
    ModelConfig,
)
from project.logger import get_logger
from project.workers.tasks import run_calibration

from . import calibrations

logger = get_logger(__name__)


def _expand_param_values(defn: dict) -> list:
    """Expand a frontend param-grid definition into a flat list of candidate values."""
    import math

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
@jwt_required()
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
        result.append(d)

    return jsonify(
        {"items": result, "total": runs.total, "page": page, "pages": runs.pages}
    ), 200


@calibrations.post("/")
@jwt_required()
def create_run():
    body = request.get_json(silent=True) or {}
    required = ("dataset_id", "model_config_id")
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {missing}"}), 400

    ds = Dataset.query.get(body["dataset_id"])
    cfg = ModelConfig.query.get(body["model_config_id"])
    if not ds:
        return jsonify({"error": "Dataset not found"}), 404
    if not cfg:
        return jsonify({"error": "ModelConfig not found"}), 404

    # Build CV search config if provided
    cv_search = body.get("cv_search")
    param_grid_raw = body.get("param_grid") or {}
    search_config_json = None
    if cv_search and cv_search.get("mode", "none") != "none":
        param_grid = {}
        for param_name, defn in param_grid_raw.items():
            if not defn or not defn.get("enabled"):
                continue
            values = _expand_param_values(defn)
            if values:
                param_grid[param_name] = values
        if param_grid:
            search_config_json = json.dumps(
                {
                    "type": cv_search.get("mode", "grid"),
                    "param_grid": param_grid,
                    "cv": int(cv_search.get("folds", 5)),
                    "scoring": cv_search.get("scoring", "roc_auc"),
                    "n_iter": int(cv_search.get("nIter", 20)),
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
        )
        session.add(run)
        session.flush()
        result = run.to_dict()

    run_calibration.delay(run_id)
    return jsonify(result), 202


@calibrations.get("/<run_id>")
@jwt_required()
def get_run(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    d = run.to_dict()
    d["config_name"] = run.model_config.name if run.model_config else None
    d["dataset_name"] = run.dataset.name if run.dataset else None
    d["algorithm"] = run.model_config.algorithm if run.model_config else None
    return jsonify(d), 200


@calibrations.get("/<run_id>/diagnostics")
@jwt_required()
def get_diagnostics(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    if run.status != "success":
        return jsonify(
            {"error": f"Run is {run.status}, diagnostics not available"}
        ), 409
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
@jwt_required()
def get_forecast(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    forecasts = (
        Forecast.query.filter_by(calibration_run_id=run.id)
        .order_by(Forecast.created_at)
        .all()
    )
    return jsonify([f.to_dict() for f in forecasts]), 200


@calibrations.post("/<run_id>/cancel")
@jwt_required()
def cancel_run(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    if run.status not in ("queued", "running"):
        return jsonify({"error": f"Cannot cancel a run with status {run.status}"}), 409
    with app_session() as s:
        r = CalibrationRun.query.filter_by(run_id=run_id).first()
        r.status = "failed"
        r.finished_at = datetime.now(timezone.utc)
        r.error_message = "Cancelled by user"
        s.add(r)
        s.flush()
        result = r.to_dict()
    return jsonify(result), 200


@calibrations.get("/<run_id>/logs")
@jwt_required()
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


@calibrations.delete("/<run_id>")
@jwt_required()
def delete_run(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    if run.status in ("queued", "running"):
        return jsonify({"error": "Cannot delete an active run — cancel it first"}), 409
    with app_session() as s:
        s.delete(CalibrationRun.query.filter_by(run_id=run_id).first())
    return "", 204


@calibrations.post("/bulk-delete")
@jwt_required()
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
        with app_session() as s:
            s.delete(CalibrationRun.query.filter_by(run_id=rid).first())
        deleted.append(rid)

    return jsonify({"deleted": len(deleted), "skipped": len(skipped)}), 200


@calibrations.post("/<run_id>/recalibrate")
@jwt_required()
def recalibrate(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    if run.status in ("queued", "running"):
        return jsonify({"error": "Run is already active"}), 409

    with app_session() as s:
        r = CalibrationRun.query.filter_by(run_id=run_id).first()
        # Clear previous results and reset to queued
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
        # Delete previous log lines so the progress tab starts fresh
        CalibrationRunLog.query.filter_by(run_id=run_id).delete()
        s.flush()
        result = r.to_dict()

    run_calibration.delay(run_id)
    return jsonify(result), 202
