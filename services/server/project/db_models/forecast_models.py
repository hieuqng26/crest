from datetime import datetime, timezone

from project import db


class ForecastRun(db.Model):
    __tablename__ = "forecast_runs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(128), nullable=True)
    calibration_run_id = db.Column(
        db.Integer,
        db.ForeignKey("calibration_runs.id"),
        nullable=False,
    )
    dataset_id = db.Column(db.Integer, db.ForeignKey("datasets.id"), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="queued")
    triggered_by = db.Column(db.String(64), nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    progress = db.Column(db.Integer, nullable=False, default=0)

    segment_key = db.Column(db.String(128), nullable=True)
    workflow_run_id = db.Column(
        db.Integer, db.ForeignKey("workflow_runs.id"), nullable=True, index=True
    )

    results = db.relationship(
        "ForecastRunResult", cascade="all, delete-orphan", lazy="dynamic"
    )

    def to_dict(self, *, cal_run=None, dataset=None, config_name=None):
        """Serialise the run.

        Callers that already hold the related rows (list/detail endpoints that
        batch-load them) can pass ``cal_run``, ``dataset`` and ``config_name`` to
        avoid the three per-row ``.query.get()`` lookups this method would
        otherwise fire. Single-item callers omit them and get the self-contained
        path below.
        """
        from project.db_models.calibration_models import (
            CalibrationRun,
            Dataset,
            ModelConfig,
        )

        if cal_run is None:
            cal_run = CalibrationRun.query.get(self.calibration_run_id)
        if dataset is None:
            dataset = Dataset.query.get(self.dataset_id)
        ds = dataset

        target_col = None
        if cal_run:
            target_col = cal_run.target_col
            if config_name is None:
                cfg = ModelConfig.query.get(cal_run.model_config_id)
                config_name = cfg.name if cfg else None

        return dict(
            id=self.id,
            run_id=self.run_id,
            name=self.name,
            calibration_run_id=self.calibration_run_id,
            calibration_run_uuid=cal_run.run_id if cal_run else None,
            target_col=target_col,
            config_name=config_name,
            dataset_id=self.dataset_id,
            dataset_name=ds.name if ds else None,
            status=self.status,
            triggered_by=self.triggered_by,
            created_at=self.created_at.isoformat() if self.created_at else None,
            started_at=self.started_at.isoformat() if self.started_at else None,
            finished_at=self.finished_at.isoformat() if self.finished_at else None,
            error_message=self.error_message,
            progress=self.progress,
            segment_key=self.segment_key,
            workflow_run_id=self.workflow_run_id,
        )


class ForecastRunResult(db.Model):
    __tablename__ = "forecast_run_results"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    forecast_run_id = db.Column(
        db.Integer,
        db.ForeignKey("forecast_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date = db.Column(db.String(32), nullable=True)
    predicted = db.Column(db.Float, nullable=True)
    meta_json = db.Column(db.Text, nullable=True)


class ForecastRunLog(db.Model):
    __tablename__ = "forecast_run_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(db.String(64), nullable=False, index=True)
    t = db.Column(db.String(32), nullable=True)
    level = db.Column(db.String(16), nullable=False, default="info")
    message = db.Column(db.Text, nullable=False)

    def to_dict(self):
        return dict(
            id=self.id,
            run_id=self.run_id,
            t=self.t,
            level=self.level,
            message=self.message,
        )
