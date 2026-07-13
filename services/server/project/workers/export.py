"""Async file-export tasks (dedicated ``exports`` queue).

``export_dataset`` builds one workflow output into a csv/xlsx file and uploads it
to MinIO; ``purge_expired_exports`` (run by beat) reclaims expired files+rows.
Kept off the ``default`` pipeline queue so a heavy export build never delays
calibration/forecast/credit tasks (queue routing in ``project.workers.__init__``).
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from project import db
from project.constants import Progress, RunStatus
from project.core import storage
from project.logger import get_logger
from project.workers import celery_app
from project.workers.common import _make_flask_app, format_failure

logger = get_logger(__name__)


def _write_export_progress(
    job_id: str, progress: int, message: str, status: str | None = None
) -> None:
    """Update an ExportJob's progress/message (and optionally status) on an
    independent session so it never expires objects the task holds. Silent-fails
    so a progress write can never kill the export."""
    try:
        from project.db_models.export_models import ExportJob

        with Session(db.engine) as s:
            job = s.query(ExportJob).filter_by(job_id=job_id).first()
            if job:
                job.progress = max(0, progress)
                job.progress_message = message
                if status:
                    job.status = status
                s.commit()
    except Exception:
        logger.exception("_write_export_progress failed for export %s", job_id)


@celery_app.task(bind=True, name="export_dataset")
def export_dataset(self, job_id: str):
    """Build + upload one export job's file. Terminal states: success | failed."""
    from project import app_session
    from project.db_models.export_models import ExportJob
    from project.db_models.workflow_models import WorkflowRun
    from project.services import workflow_exports

    app = _make_flask_app()
    with app.app_context():
        # Resolve the job's static fields up front (a later progress write closes
        # the session and would expire the ORM object).
        job = ExportJob.query.filter_by(job_id=job_id).first()
        if not job:
            return  # already purged — idempotent no-op
        wf = WorkflowRun.query.get(job.workflow_run_id)
        if not wf:
            return
        wf_run_id = wf.run_id
        output_key = job.output_key
        fmt = job.fmt

        try:
            with app_session() as s:
                j = ExportJob.query.filter_by(job_id=job_id).first()
                j.status = RunStatus.RUNNING
                j.started_at = datetime.now(timezone.utc)
                j.progress = 5
                j.progress_message = "Building export…"
                s.add(j)

            data, filename, mimetype, row_count = workflow_exports.build_export_bytes(
                wf_run_id, output_key, fmt
            )

            _write_export_progress(job_id, 70, f"Uploading {row_count:,} rows…")
            object_name = workflow_exports.object_prefix(wf_run_id, job_id) + filename
            object_path = storage.upload_bytes(object_name, data, mimetype)

            with app_session() as s:
                j = ExportJob.query.filter_by(job_id=job_id).first()
                j.status = RunStatus.SUCCESS
                j.progress = Progress.COMPLETE
                j.progress_message = "Ready to download"
                j.object_path = object_path
                j.filename = filename
                j.mimetype = mimetype
                j.row_count = row_count
                j.file_size = len(data)
                j.finished_at = datetime.now(timezone.utc)
                j.expires_at = workflow_exports.retention_expiry()
                s.add(j)

        except Exception as exc:
            logger.error("Export job %s failed: %s", job_id, exc, exc_info=True)
            with app_session() as s:
                j = ExportJob.query.filter_by(job_id=job_id).first()
                if j:
                    j.status = RunStatus.FAILED
                    j.progress = Progress.FAILED
                    j.progress_message = f"Failed: {exc}"
                    j.error_message = format_failure(exc)
                    j.finished_at = datetime.now(timezone.utc)
                    s.add(j)
            raise


@celery_app.task(name="purge_expired_exports")
def purge_expired_exports():
    """Delete expired export files + rows (beat sweep). Returns the count."""
    from project.services import workflow_exports

    app = _make_flask_app()
    with app.app_context():
        removed = workflow_exports.purge_expired()
        if removed:
            logger.info("Purged %d expired export job(s)", removed)
        return removed
