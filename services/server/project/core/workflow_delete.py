"""Bulk, set-based deletion of a workflow and every run it owns.

``delete_workflow`` (the API route) validates that a workflow is safe to delete
and flips its status to ``deleting``; the actual purge runs here, driven by the
``delete_workflow`` Celery task so a large workflow never blocks the request.

Why set-based deletes: ``WorkflowRun`` has no ORM ``relationship()`` to its child
runs (the ``workflow_run_id`` FKs are bare columns), so the per-row ORM cascade
path SELECTed and DELETEd every child row one at a time — thousands of round-trips
to MSSQL for the heavy result/log tables. Here we issue one
``DELETE ... WHERE col IN (...)`` per table instead, child-first in FK order.
Each ``.delete()`` executes immediately within the transaction, so issuing them
in dependency order keeps every statement FK-valid without needing flushes.
"""

from project import app_session
from project.core import storage
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunLog,
    CalibrationRunSegment,
    Forecast,
    ForecastResult,
)
from project.db_models.credit_models import (
    CreditRiskAnalysisSeries,
    CreditRiskForecastInput,
    CreditRiskResult,
    CreditRiskRun,
    CreditRiskRunLog,
)
from project.db_models.export_models import ExportJob
from project.db_models.forecast_models import (
    ForecastRun,
    ForecastRunLog,
    ForecastRunResult,
)
from project.db_models.workflow_models import WorkflowRun
from project.logger import get_logger

logger = get_logger(__name__)


def purge_workflow(wf_id: int) -> None:
    """Delete a workflow and all of its calibration/forecast/credit-risk runs,
    their result/log/segment rows, and the MinIO artifacts of its calibration
    runs. Idempotent: a missing workflow is a no-op.

    Must run inside a Flask app context (the Celery task provides one).
    """
    wf = WorkflowRun.query.filter_by(id=wf_id).first()
    wf_run_uuid = wf.run_id if wf else None

    cals = CalibrationRun.query.filter_by(workflow_run_id=wf_id).all()
    fcs = ForecastRun.query.filter_by(workflow_run_id=wf_id).all()
    crs = CreditRiskRun.query.filter_by(workflow_run_id=wf_id).all()

    cal_ids = [c.id for c in cals]
    cal_uuids = [c.run_id for c in cals]
    fr_ids = [fr.id for fr in fcs]
    fr_uuids = [fr.run_id for fr in fcs]
    cr_ids = [cr.id for cr in crs]
    cr_uuids = [cr.run_id for cr in crs]

    def _bulk_delete(model, column, values):
        """Emit a single set-based DELETE; skip empty id lists (an empty IN ()
        would delete nothing but still round-trips)."""
        if not values:
            return 0
        return model.query.filter(column.in_(values)).delete(synchronize_session=False)

    # app_session() gives us the transactional commit/rollback wrapper; the
    # bulk .delete() calls run through the same scoped db.session it manages.
    with app_session():
        # --- Level 1: leaf result / log / join tables (child-most first) ---
        _bulk_delete(CreditRiskResult, CreditRiskResult.run_id, cr_uuids)
        _bulk_delete(CreditRiskRunLog, CreditRiskRunLog.run_id, cr_uuids)
        _bulk_delete(
            CreditRiskAnalysisSeries,
            CreditRiskAnalysisSeries.credit_risk_run_id,
            cr_ids,
        )
        _bulk_delete(
            CreditRiskForecastInput,
            CreditRiskForecastInput.credit_risk_run_id,
            cr_ids,
        )
        _bulk_delete(ForecastRunResult, ForecastRunResult.forecast_run_id, fr_ids)
        _bulk_delete(ForecastRunLog, ForecastRunLog.run_id, fr_uuids)

        # ForecastResult -> Forecast (calibration-run children)
        if cal_ids:
            forecast_ids = [
                f.id
                for f in Forecast.query.filter(
                    Forecast.calibration_run_id.in_(cal_ids)
                ).all()
            ]
            _bulk_delete(ForecastResult, ForecastResult.forecast_id, forecast_ids)
            _bulk_delete(Forecast, Forecast.calibration_run_id, cal_ids)

        _bulk_delete(CalibrationRunLog, CalibrationRunLog.run_id, cal_uuids)
        _bulk_delete(
            CalibrationRunSegment, CalibrationRunSegment.calibration_run_id, cal_ids
        )

        # Async download exports for this workflow (independent of the runs above).
        _bulk_delete(ExportJob, ExportJob.workflow_run_id, [wf_id])

        # --- Level 2: the run tables themselves ---
        _bulk_delete(CreditRiskRun, CreditRiskRun.id, cr_ids)
        _bulk_delete(ForecastRun, ForecastRun.id, fr_ids)
        _bulk_delete(CalibrationRun, CalibrationRun.id, cal_ids)

        # --- Level 3: the workflow row ---
        WorkflowRun.query.filter_by(id=wf_id).delete(synchronize_session=False)

    # --- MinIO artifact cleanup (after the DB commit; best-effort) ---
    # Model pickles and per-segment pickles both live under artifacts/{run_id}/,
    # so removing that prefix per calibration run covers everything.
    for run_uuid in cal_uuids:
        storage.remove_prefix(f"artifacts/{run_uuid}/")

    # Generated download-export files for this workflow.
    if wf_run_uuid:
        storage.remove_prefix(f"exports/{wf_run_uuid}/")

    logger.info(
        "Purged workflow %s: %d calibration, %d forecast, %d credit-risk runs",
        wf_id,
        len(cal_ids),
        len(fr_ids),
        len(cr_ids),
    )


__all__ = ["purge_workflow"]
