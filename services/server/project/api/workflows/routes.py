import io
from datetime import datetime, timezone

import pandas as pd
from flask import jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity

from project import app_session
from project.api.auditlog.decorators import audit_action
from project.api.auth.decorators import current_permissions, require_perm
from project.api.auth.permissions import has_permission
from project.core import storage, table_query
from project.schemas.workflows import CreateWorkflow
from project.services import workflow_exports as export_service
from project.services import workflows as workflow_service
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunSegment,
)
from project.db_models.credit_models import (
    CreditRiskForecastInput,
    CreditRiskRun,
)
from project.db_models.forecast_models import ForecastRun
from project.db_models.workflow_models import WorkflowRun
from project.workers.tasks import delete_workflow as delete_workflow_task
from project.workers.tasks import export_dataset as export_dataset_task

from . import workflows


@workflows.get("/resolve-datasets")
@require_perm("calibration:read")
def resolve_datasets():
    result = {}
    for key in ("calibration", "forecast", "credit", "financial_portfolio"):
        ds = workflow_service.latest_dataset(key)
        result[key] = ds.to_dict() if ds else None
    return jsonify(result), 200


@workflows.get("/")
@require_perm("calibration:read")
def list_workflows():
    return jsonify(
        workflow_service.list_workflows(
            page=request.args.get("page", 1, type=int),
            per_page=request.args.get("per_page", 50, type=int),
        )
    ), 200


@workflows.get("/<run_id>")
@require_perm("calibration:read")
def get_workflow(run_id):
    light = request.args.get("light") in ("1", "true")
    return jsonify(workflow_service.get_workflow(run_id, light=light)), 200


@workflows.get("/<run_id>/logs")
@require_perm("calibration:read")
def get_workflow_logs(run_id):
    return jsonify(
        workflow_service.get_workflow_logs(
            run_id,
            page=int(request.args.get("page", 0)),
            page_size=int(request.args.get("page_size", 50)),
            sort_column=request.args.get("sort_column"),
            sort_order=request.args.get("sort_order"),
            filters=table_query.parse_filters(request.args.get("filters")),
        )
    ), 200


@workflows.get("/<run_id>/logs/distinct")
@require_perm("calibration:read")
def get_workflow_logs_distinct(run_id):
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404
    column = request.args.get("column", "")
    if not column:
        return jsonify({"values": [], "truncated": False}), 200
    return jsonify(
        table_query.distinct_values(workflow_service.workflow_log_df(wf), column)
    ), 200


@workflows.get("/<run_id>/forecast-results")
@require_perm("forecast:read")
def get_workflow_forecast_results(run_id):
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404
    df = workflow_service.combined_forecast_df(wf)
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


@workflows.get("/<run_id>/forecast-results/distinct")
@require_perm("forecast:read")
def get_workflow_forecast_results_distinct(run_id):
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404
    column = request.args.get("column", "")
    if not column:
        return jsonify({"values": [], "truncated": False}), 200
    return jsonify(
        table_query.distinct_values(workflow_service.combined_forecast_df(wf), column)
    ), 200


# ── Downloadable exports ────────────────────────────────────────────────────────
# The Download tab: list a workflow's exportable outputs, request an async build
# (csv/xlsx) on the dedicated `exports` queue, poll the job, and stream the file.


@workflows.get("/<run_id>/exports/outputs")
@require_perm("calibration:read")
def list_export_outputs(run_id):
    return jsonify({"outputs": export_service.list_outputs(run_id)}), 200


@workflows.get("/<run_id>/exports")
@require_perm("calibration:read")
def list_exports(run_id):
    return jsonify({"jobs": export_service.list_export_jobs(run_id)}), 200


@workflows.post("/<run_id>/exports")
@require_perm("calibration:read")
@audit_action(
    "Export",
    "models",
    "workflow",
    database_involved="workflow_export_jobs",
    describe=lambda kw, body: (
        f"User [$USER] created export job {(body or {}).get('job_id', '')} "
        f"for workflow {kw.get('run_id')}"
    ),
)
def create_export(run_id):
    body = request.get_json(silent=True) or {}
    output_key = body.get("output")
    fmt = body.get("format")

    # Enforce the output's own read permission (calibration/forecast/credit_risk).
    if output_key in export_service.OUTPUTS:
        perm = export_service.OUTPUTS[output_key]["perm"]
        if not has_permission(current_permissions(), perm):
            return jsonify({"error": f"Requires {perm} permission"}), 403

    job = export_service.create_export_job(run_id, output_key, fmt, get_jwt_identity())
    # Dispatch only newly-queued builds; a reused running/successful job is left
    # as-is (the commit inside create_export_job has already landed).
    if job.get("status") == "queued":
        export_dataset_task.apply_async(args=[job["job_id"]], queue="exports")
    return jsonify(job), 202


@workflows.get("/<run_id>/exports/<job_id>")
@require_perm("calibration:read")
def get_export(run_id, job_id):
    return jsonify(export_service.get_export_job(job_id)), 200


@workflows.get("/<run_id>/exports/<job_id>/download")
@require_perm("calibration:read")
@audit_action(
    "Download",
    "models",
    "workflow",
    database_involved="workflow_export_jobs",
    describe=lambda kw, body: (
        f"User [$USER] downloaded export {kw.get('job_id')} "
        f"for workflow {kw.get('run_id')}"
    ),
)
def download_export(run_id, job_id):
    job = export_service.get_download_target(run_id, job_id)
    perm = export_service.output_perm(job.output_key)
    if not has_permission(current_permissions(), perm):
        return jsonify({"error": f"Requires {perm} permission"}), 403

    data = storage.download_bytes(job.object_path.split("/", 1)[-1])
    return send_file(
        io.BytesIO(data),
        mimetype=job.mimetype or "application/octet-stream",
        as_attachment=True,
        download_name=job.filename or f"{job.output_key}.{job.fmt}",
    )


@workflows.post("/")
@require_perm("calibration:execute")
@audit_action(
    "Launch",
    "models",
    "workflow",
    database_involved="workflow_runs",
    describe=lambda kw, body: (
        f"User [$USER] launched workflow {(body or {}).get('run_id', '')}"
    ),
)
def create_workflow():
    perms = current_permissions()
    if not (
        has_permission(perms, "forecast:execute")
        and has_permission(perms, "credit_risk:execute")
    ):
        return jsonify(
            {
                "error": "Launching a workflow requires calibration, forecast and "
                "credit_risk execute permissions"
            }
        ), 403

    payload = CreateWorkflow.model_validate(request.get_json(silent=True) or {})
    wf_dict = workflow_service.create_workflow(payload, get_jwt_identity())
    return jsonify(wf_dict), 202


@workflows.post("/<run_id>/cancel")
@require_perm("calibration:write")
@audit_action(
    "Cancel",
    "models",
    "workflow",
    database_involved="workflow_runs",
    describe=lambda kw, body: f"User [$USER] cancelled workflow {kw.get('run_id')}",
)
def cancel_workflow(run_id):
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404
    if wf.status not in ("queued", "running"):
        return jsonify(
            {"error": f"Cannot cancel a workflow with status '{wf.status}'"}
        ), 409

    with app_session() as s:
        for cal in CalibrationRun.query.filter_by(workflow_run_id=wf.id).all():
            if cal.status in ("queued", "running"):
                cal.status = "failed"
                cal.finished_at = datetime.now(timezone.utc)
                cal.error_message = "Cancelled by user"
                s.add(cal)
        for fr in ForecastRun.query.filter_by(workflow_run_id=wf.id).all():
            if fr.status in ("queued", "running"):
                fr.status = "failed"
                fr.finished_at = datetime.now(timezone.utc)
                fr.error_message = "Cancelled by user"
                s.add(fr)
        for cr in CreditRiskRun.query.filter_by(workflow_run_id=wf.id).all():
            if cr.status in ("queued", "running"):
                cr.status = "failed"
                cr.finished_at = datetime.now(timezone.utc)
                cr.error_message = "Cancelled by user"
                s.add(cr)

        wf.status = "failed"
        wf.finished_at = datetime.now(timezone.utc)
        wf.error_message = "Cancelled by user"
        s.add(wf)
        result = wf.to_dict()

    return jsonify(result), 200


@workflows.post("/<run_id>/rerun")
@require_perm("calibration:execute")
@audit_action(
    "Rerun",
    "models",
    "workflow",
    database_involved="workflow_runs",
    describe=lambda kw, body: f"User [$USER] re-ran workflow {kw.get('run_id')}",
)
def rerun_workflow(run_id):
    perms = current_permissions()
    if not (
        has_permission(perms, "forecast:execute")
        and has_permission(perms, "credit_risk:execute")
    ):
        return jsonify(
            {
                "error": "Launching a workflow requires calibration, forecast and "
                "credit_risk execute permissions"
            }
        ), 403

    wf_dict = workflow_service.rerun_workflow(run_id, get_jwt_identity())
    return jsonify(wf_dict), 202


@workflows.put("/<run_id>/activate")
@require_perm("credit_risk:write")
@audit_action(
    "Activate",
    "models",
    "workflow",
    database_involved="workflow_runs,credit_risk_runs",
    describe=lambda kw, body: (
        f"User [$USER] activated credit risk run of workflow {kw.get('run_id')}"
    ),
)
def activate_workflow(run_id):
    """Set the workflow's credit risk run as the active analysis run,
    deactivating all others. Returns 404 if the workflow has no credit run."""
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404

    cr = CreditRiskRun.query.filter_by(workflow_run_id=wf.id).first()
    if not cr:
        return jsonify({"error": "This workflow has no credit risk run"}), 404
    if cr.status != "success":
        return jsonify({"error": "Credit risk run has not completed successfully"}), 422

    cr_run_id = cr.run_id
    with app_session() as s:
        CreditRiskRun.query.update({CreditRiskRun.is_active: False})
        cr_obj = s.get(CreditRiskRun, cr.id)
        cr_obj.is_active = True
        s.add(cr_obj)

    return jsonify({"activated": cr_run_id}), 200


@workflows.delete("/<run_id>")
@require_perm("calibration:write")
@audit_action(
    "Delete",
    "models",
    "workflow",
    database_involved="workflow_runs",
    describe=lambda kw, body: f"User [$USER] deleted workflow {kw.get('run_id')}",
)
def delete_workflow(run_id):
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404

    cals = CalibrationRun.query.filter_by(workflow_run_id=wf.id).all()
    fcs = ForecastRun.query.filter_by(workflow_run_id=wf.id).all()
    crs = CreditRiskRun.query.filter_by(workflow_run_id=wf.id).all()

    active = [r for r in (*cals, *fcs, *crs) if r.status in ("queued", "running")]
    if active:
        return jsonify(
            {"error": "Cannot delete a workflow with an active run — cancel it first"}
        ), 409

    # A segment re-run keeps its parent run at "success", so it doesn't show up
    # in the check above — but its worker is still writing to this workflow's
    # rows and artifacts, so deletion must wait for it too.
    if cals:
        retraining = CalibrationRunSegment.query.filter(
            CalibrationRunSegment.calibration_run_id.in_([c.id for c in cals]),
            CalibrationRunSegment.status.in_(("queued", "running")),
        ).first()
        if retraining:
            return jsonify(
                {
                    "error": "Cannot delete a workflow while a segment model is "
                    "re-training — wait for it to finish"
                }
            ), 409

    fr_ids = [fr.id for fr in fcs]
    outside_refs = (
        CreditRiskForecastInput.query.filter(
            CreditRiskForecastInput.forecast_run_id.in_(fr_ids)
        ).all()
        if fr_ids
        else []
    )
    outside_cr_ids = {inp.credit_risk_run_id for inp in outside_refs} - {
        cr.id for cr in crs
    }
    if outside_cr_ids:
        return jsonify(
            {
                "error": "This workflow's forecast runs are referenced by credit "
                "risk job(s) outside this workflow. Delete those first."
            }
        ), 409

    # Safe to delete. The actual purge (set-based deletes of potentially tens of
    # thousands of result/log rows + MinIO artifact cleanup) can be slow, so run
    # it in a Celery task: flip the workflow to "deleting" and return 202
    # immediately. The frontend polls the list and shows a "Deleting…" state
    # until the row disappears. Dispatch only after the status commit, so the
    # worker never sees a stale status (mirrors the launch dispatch rule).
    with app_session() as s:
        wf.status = "deleting"
        s.add(wf)
        result = wf.to_dict()

    delete_workflow_task.delay(run_id)
    return jsonify(result), 202
