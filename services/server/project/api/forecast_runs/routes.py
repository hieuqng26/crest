import uuid
from datetime import datetime, timezone

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from project.api.auth.decorators import require_perm
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunSegment,
    Dataset,
)
from project.db_models.credit_models import CreditRiskForecastInput, CreditRiskRun
from project.db_models.forecast_models import (
    ForecastRun,
    ForecastRunLog,
    ForecastRunResult,
)

from . import forecast_runs


@forecast_runs.get("")
@require_perm("forecast:read")
def list_runs():
    status = request.args.get("status")
    q = ForecastRun.query
    if status:
        q = q.filter_by(status=status)
    runs = q.order_by(ForecastRun.created_at.desc()).all()
    return jsonify([r.to_dict() for r in runs]), 200


@forecast_runs.post("")
@require_perm("forecast:execute")
def create_run():
    from project import app_session
    from project.workers.tasks import run_forecast

    body = request.get_json(silent=True) or {}
    calibration_run_id = body.get("calibration_run_id")
    dataset_id = body.get("dataset_id")

    if not calibration_run_id:
        return jsonify({"error": "calibration_run_id is required"}), 400
    if not dataset_id:
        return jsonify({"error": "dataset_id is required"}), 400

    segment_key = body.get("segment_key") or None

    cal_run = CalibrationRun.query.filter_by(run_id=calibration_run_id).first()
    if not cal_run:
        return jsonify({"error": "Calibration run not found"}), 404
    if cal_run.status != "success":
        return jsonify({"error": "Calibration run must be in success status"}), 400

    if segment_key:
        # Per-segment forecast run: validate the specific segment exists and succeeded
        seg = CalibrationRunSegment.query.filter_by(
            calibration_run_id=cal_run.id, segment_key=segment_key
        ).first()
        if not seg:
            return jsonify(
                {
                    "error": f"Segment '{segment_key}' not found under this calibration run"
                }
            ), 404
        if seg.status != "success":
            return jsonify(
                {"error": f"Segment '{segment_key}' has not completed successfully"}
            ), 400
    else:
        # No segment_key: segmented runs score every trained segment against the
        # forecast dataset (one trajectory per segment); non-segmented runs need the
        # top-level artifact.
        if not cal_run.seg_sectors_json and not cal_run.artifact_path:
            return jsonify(
                {"error": "Calibration run has no saved model artifact"}
            ), 400

    ds = Dataset.query.get(int(dataset_id))
    if not ds:
        return jsonify({"error": "Dataset not found"}), 404
    if not ds.file_path:
        return jsonify(
            {"error": "Dataset has no file — live query results are not supported"}
        ), 400

    run_id = str(uuid.uuid4())
    name = body.get("name") or None
    identity = get_jwt_identity()

    fr = ForecastRun(
        run_id=run_id,
        name=name,
        calibration_run_id=cal_run.id,
        dataset_id=int(dataset_id),
        segment_key=segment_key,
        status="queued",
        triggered_by=identity,
        created_at=datetime.now(timezone.utc),
        progress=0,
    )
    with app_session() as s:
        s.add(fr)
        s.flush()
        fr_dict = fr.to_dict()

    run_forecast.delay(run_id)
    return jsonify(fr_dict), 202


@forecast_runs.get("/<run_id>")
@require_perm("forecast:read")
def get_run(run_id: str):
    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404
    return jsonify(fr.to_dict()), 200


@forecast_runs.get("/<run_id>/refs")
@require_perm("forecast:read")
def get_refs(run_id: str):
    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404
    inputs = CreditRiskForecastInput.query.filter_by(forecast_run_id=fr.id).all()
    cr_run_ids = list({inp.credit_risk_run_id for inp in inputs})
    cr_runs = (
        CreditRiskRun.query.filter(CreditRiskRun.id.in_(cr_run_ids)).all()
        if cr_run_ids
        else []
    )
    return jsonify(
        {
            "credit_risk_runs": [
                {"run_id": r.run_id, "status": r.status, "is_active": r.is_active}
                for r in cr_runs
            ]
        }
    ), 200


def _cr_refs_for(fr_id: int):
    """Return CreditRiskRun objects that reference this forecast run id."""
    inputs = CreditRiskForecastInput.query.filter_by(forecast_run_id=fr_id).all()
    cr_run_ids = list({inp.credit_risk_run_id for inp in inputs})
    return (
        CreditRiskRun.query.filter(CreditRiskRun.id.in_(cr_run_ids)).all()
        if cr_run_ids
        else []
    )


@forecast_runs.delete("/<run_id>")
@require_perm("forecast:write")
def delete_run(run_id: str):
    from project import app_session

    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404

    cr_runs = _cr_refs_for(fr.id)
    if cr_runs:
        return jsonify(
            {
                "error": f"This forecast run is referenced by {len(cr_runs)} credit risk job(s). "
                "Delete those jobs first.",
                "credit_risk_run_ids": [r.run_id for r in cr_runs],
            }
        ), 409

    with app_session() as s:
        r = ForecastRun.query.filter_by(run_id=run_id).first()
        if r:
            s.delete(r)

    return jsonify({"ok": True}), 200


@forecast_runs.post("/bulk-delete")
@require_perm("forecast:write")
def bulk_delete_runs():
    from project import app_session

    run_ids = (request.get_json(silent=True) or {}).get("run_ids", [])
    if not run_ids:
        return jsonify({"error": "run_ids is required"}), 400

    deleted, skipped = [], []
    for rid in run_ids:
        fr = ForecastRun.query.filter_by(run_id=rid).first()
        if not fr:
            continue
        if fr.status in ("queued", "running"):
            skipped.append(rid)
            continue
        if _cr_refs_for(fr.id):
            skipped.append(rid)
            continue
        with app_session() as s:
            obj = ForecastRun.query.filter_by(run_id=rid).first()
            if obj:
                s.delete(obj)
        deleted.append(rid)

    return jsonify(
        {"deleted": len(deleted), "deleted_ids": deleted, "skipped": len(skipped)}
    ), 200


@forecast_runs.post("/<run_id>/cancel")
@require_perm("forecast:execute")
def cancel_run(run_id: str):
    from project import app_session

    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404
    if fr.status not in ("queued", "running"):
        return jsonify({"error": f"Cannot cancel a run with status '{fr.status}'"}), 409

    with app_session() as s:
        r = ForecastRun.query.filter_by(run_id=run_id).first()
        r.status = "failed"
        r.finished_at = datetime.now(timezone.utc)
        r.error_message = "Cancelled by user"
        s.add(r)
        s.flush()
        result = r.to_dict()

    return jsonify(result), 200


@forecast_runs.get("/<run_id>/logs")
@require_perm("forecast:read")
def get_logs(run_id: str):
    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404
    logs = (
        ForecastRunLog.query.filter_by(run_id=run_id).order_by(ForecastRunLog.id).all()
    )
    return jsonify([log.to_dict() for log in logs]), 200


@forecast_runs.post("/<run_id>/rerun")
@require_perm("forecast:execute")
def rerun_run(run_id: str):
    from project import app_session
    from project.workers.tasks import run_forecast

    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404

    with app_session() as s:
        r = ForecastRun.query.filter_by(run_id=run_id).first()
        ForecastRunResult.query.filter_by(forecast_run_id=r.id).delete()
        r.status = "queued"
        r.progress = 0
        r.started_at = None
        r.finished_at = None
        r.error_message = None
        s.add(r)

    run_forecast.delay(run_id)
    return jsonify({"ok": True}), 202


@forecast_runs.get("/<run_id>/results")
@require_perm("forecast:read")
def get_results(run_id: str):
    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404

    rows = (
        ForecastRunResult.query.filter_by(forecast_run_id=fr.id)
        .order_by(ForecastRunResult.id)
        .all()
    )
    result = [
        {
            "date": r.date,
            "predicted": r.predicted,
            "meta": r.meta_json,
        }
        for r in rows
    ]
    return jsonify({"rows": result, "total": len(result)}), 200
