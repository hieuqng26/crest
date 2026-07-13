from datetime import datetime, timezone

from project import db
from project.db_models.base_model import SerializerMixin


class ExportJob(db.Model, SerializerMixin):
    """An asynchronous download-file build for one workflow output.

    A user requests an output (model_predictions / forecast_results /
    credit_results) in a format (csv|xlsx); the ``export_dataset`` Celery task
    (on the dedicated ``exports`` queue) builds the DataFrame, encodes it, and
    uploads the file to MinIO under ``exports/{workflow_run_id}/{job_id}/``.
    The row carries the job's lifecycle (mirroring the ``*_runs`` tables) plus
    the resulting object path so the download route can stream it. Files (and
    these rows) are reclaimed after ``expires_at`` by the ``purge_expired_exports``
    beat task.
    """

    __tablename__ = "export_jobs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    job_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    workflow_run_id = db.Column(
        db.Integer, db.ForeignKey("workflow_runs.id"), nullable=False, index=True
    )
    output_key = db.Column(db.String(64), nullable=False)
    fmt = db.Column(db.String(8), nullable=False)  # csv|xlsx

    status = db.Column(
        db.String(32), nullable=False, default="queued"
    )  # queued|running|success|failed
    progress = db.Column(db.Integer, nullable=False, default=0)
    progress_message = db.Column(db.String(512), nullable=True)

    object_path = db.Column(db.String(512), nullable=True)  # "{bucket}/exports/..."
    filename = db.Column(db.String(255), nullable=True)  # download name
    mimetype = db.Column(db.String(128), nullable=True)
    row_count = db.Column(db.Integer, nullable=True)
    file_size = db.Column(db.Integer, nullable=True)

    error_message = db.Column(db.Text, nullable=True)
    triggered_by = db.Column(db.String(255), nullable=True)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
