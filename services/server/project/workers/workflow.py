import json
import uuid
from datetime import datetime, timezone


from project.workers import celery_app
from project.workers.common import (
    REQUIRED_SLOTS,
    SLOT_BY_TARGET,
    _make_flask_app,
    format_failure,
)


from project.logger import get_logger

logger = get_logger(__name__)


def advance_workflow_impl(workflow_run_id: int):
    """Check a workflow's children and advance it to its next stage, or
    finalize it as failed/success. Called after every status transition
    (running/success/failed) on a workflow's calibration/forecast/credit-risk
    children.

    DB-driven completion-check pattern rather than a Celery chain/chord: each
    child task already owns its own status transitions, so this just re-reads
    the workflow's children on every call and decides what (if anything) the
    workflow should do next. The workflow row is locked for the duration of
    the check via SELECT ... FOR UPDATE (a no-op hint on SQLite, used in
    tests), and `current_stage` acts as a guard — two children finishing at
    the same instant both call this, but the second call sees the stage the
    first one already advanced to and does nothing.
    """
    from project.workers.credit import (
        run_credit_analysis,
    )  # deferred: avoids import cycle
    from project.workers.forecast import run_forecast  # deferred: avoids import cycle

    from project import app_session
    from project.db_models.calibration_models import CalibrationRun
    from project.db_models.credit_models import CreditRiskForecastInput, CreditRiskRun
    from project.db_models.forecast_models import ForecastRun
    from project.db_models.workflow_models import WorkflowRun

    to_dispatch: list[tuple[str, str]] = []

    with app_session() as s:
        wf = WorkflowRun.query.filter_by(id=workflow_run_id).with_for_update().first()
        if not wf or wf.status in ("success", "failed"):
            return  # terminal or missing — idempotent no-op

        cals = CalibrationRun.query.filter_by(workflow_run_id=wf.id).all()
        fcs = ForecastRun.query.filter_by(workflow_run_id=wf.id).all()
        crs = CreditRiskRun.query.filter_by(workflow_run_id=wf.id).all()

        def _first_failed(runs, stage_label):
            for r in runs:
                if r.status == "failed":
                    label = getattr(r, "target_col", None) or r.run_id
                    return stage_label, label, r.error_message
            return None

        failed = (
            _first_failed(cals, "Training")
            or _first_failed(fcs, "Forecast")
            or _first_failed(crs, "Credit analysis")
        )
        if failed:
            stage_label, label, err = failed
            wf.status = "failed"
            wf.finished_at = datetime.now(timezone.utc)
            wf.error_message = (
                f"{stage_label} failed for '{label}': {err or 'unknown error'}"
            )
            s.add(wf)
            return

        if wf.status == "queued":
            # Reaching this point means the workflow isn't failed/finished, so
            # some child has moved past "queued" — reflect that even if the
            # triggering child raced ahead to "success" before we got here.
            wf.status = "running"
            wf.started_at = wf.started_at or datetime.now(timezone.utc)
            s.add(wf)

        if (
            wf.current_stage == "training"
            and cals
            and all(c.status == "success" for c in cals)
        ):
            for cal in cals:
                fr = ForecastRun(
                    run_id=str(uuid.uuid4()),
                    name=f"{wf.name} · {cal.target_col}",
                    calibration_run_id=cal.id,
                    dataset_id=wf.forecast_dataset_id,
                    status="queued",
                    triggered_by=wf.triggered_by,
                    created_at=datetime.now(timezone.utc),
                    workflow_run_id=wf.id,
                )
                s.add(fr)
                s.flush()
                to_dispatch.append(("run_forecast", fr.run_id))
            wf.current_stage = "forecast"
            s.add(wf)

        elif (
            wf.current_stage == "forecast"
            and fcs
            and all(f.status == "success" for f in fcs)
        ):
            target_by_cal_id = {c.id: c.target_col for c in cals}
            slots: dict[str, ForecastRun] = {}
            for fr in fcs:
                slot = SLOT_BY_TARGET.get(target_by_cal_id.get(fr.calibration_run_id))
                if slot:
                    slots[slot] = fr
            required_slots = REQUIRED_SLOTS
            missing_slots = required_slots - set(slots.keys())

            if missing_slots or not wf.credit_dataset_id:
                if missing_slots:
                    missing_targets = [
                        t for t, sl in SLOT_BY_TARGET.items() if sl in missing_slots
                    ]
                    reason = (
                        "Credit analysis skipped — training did not include all "
                        f"required targets: {', '.join(missing_targets)}"
                    )
                else:
                    reason = (
                        "Credit analysis skipped — no credit portfolio dataset "
                        "available"
                    )
                wf.current_stage = "done"
                wf.status = "success"
                wf.finished_at = datetime.now(timezone.utc)
                wf.analysis_skipped_reason = reason
                s.add(wf)
            else:
                params = json.loads(wf.analysis_params_json or "{}")
                cr = CreditRiskRun(
                    run_id=str(uuid.uuid4()),
                    dataset_id=wf.credit_dataset_id,
                    financial_portfolio_dataset_id=wf.financial_dataset_id,
                    is_active=False,
                    exposure=float(params.get("exposure", 1_000_000)),
                    discount_rate=float(params.get("discount_rate", 0.05)),
                    lifetime_horizon=int(params.get("lifetime_horizon", 5)),
                    curve=params.get("curve", "moodys"),
                    status="queued",
                    triggered_by=wf.triggered_by,
                    created_at=datetime.now(timezone.utc),
                    workflow_run_id=wf.id,
                )
                s.add(cr)
                s.flush()
                for slot, fr in slots.items():
                    s.add(
                        CreditRiskForecastInput(
                            credit_risk_run_id=cr.id,
                            forecast_run_id=fr.id,
                            forecast_run_uuid=fr.run_id,
                            slot=slot,
                        )
                    )
                wf.current_stage = "analysis"
                s.add(wf)
                s.flush()
                to_dispatch.append(("run_credit_analysis", cr.run_id))

        elif (
            wf.current_stage == "analysis"
            and crs
            and all(c.status == "success" for c in crs)
        ):
            wf.current_stage = "done"
            wf.status = "success"
            wf.finished_at = datetime.now(timezone.utc)
            s.add(wf)

    # Dispatch only after the transaction above has committed — otherwise a
    # worker could pick up the new run before its row is visible.
    for task_name, rid in to_dispatch:
        (run_forecast if task_name == "run_forecast" else run_credit_analysis).delay(
            rid
        )


@celery_app.task(bind=True, name="advance_workflow")
def advance_workflow(self, workflow_run_id: int):
    app = _make_flask_app()
    with app.app_context():
        advance_workflow_impl(workflow_run_id)


@celery_app.task(bind=True, name="delete_workflow")
def delete_workflow(self, run_id: str):
    """Purge a workflow and all its runs in the background. The API route has
    already validated the delete is safe and flipped the workflow to the
    ``deleting`` status; this does the heavy set-based deletion + MinIO cleanup.

    On any unexpected error the workflow is reverted out of ``deleting`` to a
    ``failed`` status with the traceback, so a row can never get stuck showing
    "Deleting…" forever.
    """
    from project import app_session
    from project.core.workflow_delete import purge_workflow
    from project.db_models.workflow_models import WorkflowRun

    app = _make_flask_app()
    with app.app_context():
        wf = WorkflowRun.query.filter_by(run_id=run_id).first()
        if not wf:
            return  # already gone — idempotent no-op
        wf_id = wf.id
        try:
            purge_workflow(wf_id)
        except Exception as e:  # noqa: BLE001 - surface, never leave stuck
            logger.exception("Workflow %s deletion failed", run_id)
            with app_session() as s:
                wf = WorkflowRun.query.filter_by(id=wf_id).first()
                if wf:
                    wf.status = "failed"
                    wf.error_message = f"Deletion failed:\n{format_failure(e)}"
                    wf.finished_at = datetime.now(timezone.utc)
                    s.add(wf)
            raise
