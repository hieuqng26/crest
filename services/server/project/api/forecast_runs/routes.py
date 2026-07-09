import json
from datetime import datetime, timezone

import pandas as pd
from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from project.api.auth.decorators import require_perm
from project.api.utils import paginate_logs
from project.core import table_query
from project.db_models.calibration_models import (
    CalibrationRun,
    Dataset,
)
from project.db_models.credit_models import CreditRiskForecastInput, CreditRiskRun
from project.db_models.forecast_models import (
    ForecastRun,
    ForecastRunLog,
    ForecastRunResult,
)
from project.api.helpers import pagination_envelope
from project.schemas.forecast_runs import CreateForecastRun
from project.services import forecast_runs as forecast_run_service
from project.services.run_guards import ensure_not_workflow_member

from . import forecast_runs


@forecast_runs.get("")
@require_perm("forecast:read")
def list_runs():
    status = request.args.get("status")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    q = ForecastRun.query
    if status:
        q = q.filter_by(status=status)
    runs = q.order_by(ForecastRun.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    items = runs.items

    # Batch-load the related rows so ForecastRun.to_dict() doesn't fire three
    # per-row queries (was 1 + 3N; now a handful of IN(...) lookups).
    from project.db_models.calibration_models import ModelConfig

    cal_ids = {r.calibration_run_id for r in items}
    ds_ids = {r.dataset_id for r in items}
    cals = (
        {c.id: c for c in CalibrationRun.query.filter(CalibrationRun.id.in_(cal_ids))}
        if cal_ids
        else {}
    )
    cfg_ids = {c.model_config_id for c in cals.values()}
    cfgs = (
        {m.id: m for m in ModelConfig.query.filter(ModelConfig.id.in_(cfg_ids))}
        if cfg_ids
        else {}
    )
    datasets = (
        {d.id: d for d in Dataset.query.filter(Dataset.id.in_(ds_ids))}
        if ds_ids
        else {}
    )

    result = []
    for r in items:
        cal = cals.get(r.calibration_run_id)
        cfg = cfgs.get(cal.model_config_id) if cal else None
        result.append(
            r.to_dict(
                cal_run=cal,
                dataset=datasets.get(r.dataset_id),
                config_name=cfg.name if cfg else None,
            )
        )

    return jsonify(pagination_envelope(result, runs)), 200


@forecast_runs.post("")
@require_perm("forecast:execute")
def create_run():
    payload = CreateForecastRun.model_validate(request.get_json(silent=True) or {})
    fr_dict = forecast_run_service.create_run(payload, get_jwt_identity())
    return jsonify(fr_dict), 202


@forecast_runs.get("/<run_id>")
@require_perm("forecast:read")
def get_run(run_id: str):
    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404
    d = fr.to_dict()
    if fr.workflow_run_id:
        from project.db_models.workflow_models import WorkflowRun

        wf = WorkflowRun.query.get(fr.workflow_run_id)
        d["workflow_run_uuid"] = wf.run_id if wf else None
    return jsonify(d), 200


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

    ensure_not_workflow_member(fr)

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
        if fr.workflow_run_id:
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
        workflow_run_id = r.workflow_run_id
        s.add(r)
        s.flush()
        result = r.to_dict()

    if workflow_run_id:
        from project.workers.tasks import advance_workflow

        advance_workflow.delay(workflow_run_id)
    return jsonify(result), 200


@forecast_runs.get("/<run_id>/logs")
@require_perm("forecast:read")
def get_logs(run_id: str):
    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404
    logs = paginate_logs(
        ForecastRunLog.query.filter_by(run_id=run_id), ForecastRunLog.id
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
    ensure_not_workflow_member(fr)

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


def _forecast_results_df(fr: ForecastRun) -> pd.DataFrame:
    rows = (
        ForecastRunResult.query.filter_by(forecast_run_id=fr.id)
        .order_by(ForecastRunResult.id)
        .all()
    )
    records = []
    for r in rows:
        try:
            meta = json.loads(r.meta_json) if r.meta_json else {}
        except (TypeError, ValueError):
            meta = {}
        records.append({"date": r.date, "predicted": r.predicted, **meta})
    return pd.DataFrame.from_records(records)


@forecast_runs.get("/<run_id>/results")
@require_perm("forecast:read")
def get_results(run_id: str):
    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404

    df = _forecast_results_df(fr)
    page, total = table_query.query_page(
        df,
        page=int(request.args.get("page", 0)),
        page_size=int(request.args.get("page_size", 50)),
        sort_column=request.args.get("sort_column"),
        sort_order=request.args.get("sort_order"),
        filters=table_query.parse_filters(request.args.get("filters")),
    )
    rows = page.where(pd.notnull(page), None).to_dict(orient="records")
    columns = list(df.columns)
    return jsonify({"rows": rows, "total": total, "columns": columns}), 200


@forecast_runs.get("/<run_id>/results/distinct")
@require_perm("forecast:read")
def get_results_distinct(run_id: str):
    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        return jsonify({"error": "Not found"}), 404
    column = request.args.get("column", "")
    if not column:
        return jsonify({"values": [], "truncated": False}), 200

    df = _forecast_results_df(fr)
    return jsonify(table_query.distinct_values(df, column)), 200
