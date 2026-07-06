import json
from datetime import datetime, timezone

from project import db


class Dataset(db.Model):
    __tablename__ = "datasets"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(32), nullable=False)  # 'upload' | 'live_query'
    file_path = db.Column(db.String(1024), nullable=True)
    schema_json = db.Column(db.Text, nullable=True)
    row_count = db.Column(db.Integer, nullable=True)
    created_by = db.Column(db.String(64), db.ForeignKey("users.email"), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.now(timezone.utc)
    )
    status = db.Column(db.String(32), nullable=False, default="ready")
    kind = db.Column(db.String(32), nullable=False, default="calibration")

    calibration_runs = db.relationship("CalibrationRun", backref="dataset", lazy=True)

    def to_dict(self):
        return dict(
            id=self.id,
            name=self.name,
            description=self.description,
            source=self.source,
            file_path=self.file_path,
            schema_json=self.schema_json,
            row_count=self.row_count,
            created_by=self.created_by,
            created_at=self.created_at.isoformat() if self.created_at else None,
            status=self.status,
            kind=self.kind,
        )


class ModelConfig(db.Model):
    __tablename__ = "model_configs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    family = db.Column(
        db.String(32), nullable=False
    )  # 'classification' | 'timeseries' | 'statistical'
    algorithm = db.Column(db.String(128), nullable=False)
    hyperparams_json = db.Column(db.Text, nullable=True)
    train_split = db.Column(db.Float, nullable=False, default=0.8)
    scaler = db.Column(db.String(32), nullable=True)
    search_config_json = db.Column(db.Text, nullable=True)
    split_by = db.Column(db.String(32), nullable=False, default="subsector")
    max_segments = db.Column(db.Integer, nullable=False, default=5)
    created_by = db.Column(db.String(64), db.ForeignKey("users.email"), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.now(timezone.utc)
    )

    calibration_runs = db.relationship(
        "CalibrationRun", backref="model_config", lazy=True
    )

    def to_dict(self):
        return dict(
            id=self.id,
            name=self.name,
            family=self.family,
            algorithm=self.algorithm,
            hyperparams_json=self.hyperparams_json,
            train_split=self.train_split,
            scaler=self.scaler,
            search_config_json=self.search_config_json,
            split_by=self.split_by,
            max_segments=self.max_segments,
            created_by=self.created_by,
            created_at=self.created_at.isoformat() if self.created_at else None,
        )


class CalibrationRun(db.Model):
    __tablename__ = "calibration_runs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(
        db.String(255), nullable=True
    )  # user-facing run label; falls back to model_config.name when unset
    dataset_id = db.Column(db.Integer, db.ForeignKey("datasets.id"), nullable=False)
    model_config_id = db.Column(
        db.Integer, db.ForeignKey("model_configs.id"), nullable=False
    )
    status = db.Column(
        db.String(32), nullable=False, default="queued"
    )  # queued|running|success|failed
    triggered_by = db.Column(
        db.String(64), db.ForeignKey("users.email"), nullable=False
    )
    artifact_path = db.Column(db.String(1024), nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    train_metrics_json = db.Column(db.Text, nullable=True)
    val_metrics_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    progress = db.Column(db.Integer, nullable=False, default=0)
    progress_message = db.Column(db.String(512), nullable=True)
    search_config_json = db.Column(db.Text, nullable=True)
    best_params_json = db.Column(db.Text, nullable=True)
    train_split = db.Column(db.Float, nullable=False, default=0.8)
    scaler = db.Column(db.String(32), nullable=True)
    target_col = db.Column(db.String(255), nullable=True)
    feature_cols_json = db.Column(db.Text, nullable=True)
    secondary_dataset_ids_json = db.Column(
        db.Text, nullable=True
    )  # JSON list of int IDs
    merge_steps_json = db.Column(db.Text, nullable=True)  # JSON list of {type, on}
    seg_sectors_json = db.Column(
        db.Text, nullable=True
    )  # JSON array of sector name strings
    seg_split_by = db.Column(db.String(16), nullable=True)  # 'subsector' | 'country'
    seg_max_segments = db.Column(db.Integer, nullable=True)
    seg_sector_overrides_json = db.Column(
        db.Text, nullable=True
    )  # JSON: {sector: {split_by?, max_segments?, model_config_id?, feature_cols?}}
    workflow_run_id = db.Column(
        db.Integer, db.ForeignKey("workflow_runs.id"), nullable=True, index=True
    )

    forecasts = db.relationship(
        "Forecast", backref="calibration_run", cascade="all, delete", lazy=True
    )
    logs = db.relationship(
        "CalibrationRunLog", backref="calibration_run", cascade="all, delete", lazy=True
    )
    segments = db.relationship(
        "CalibrationRunSegment",
        backref="calibration_run",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        return dict(
            id=self.id,
            run_id=self.run_id,
            name=self.name,
            dataset_id=self.dataset_id,
            model_config_id=self.model_config_id,
            status=self.status,
            triggered_by=self.triggered_by,
            artifact_path=self.artifact_path,
            started_at=self.started_at.isoformat() if self.started_at else None,
            finished_at=self.finished_at.isoformat() if self.finished_at else None,
            train_metrics_json=self.train_metrics_json,
            val_metrics_json=self.val_metrics_json,
            error_message=self.error_message,
            progress=self.progress,
            progress_message=self.progress_message,
            search_config_json=self.search_config_json,
            best_params_json=self.best_params_json,
            train_split=self.train_split,
            scaler=self.scaler,
            target_col=self.target_col,
            feature_cols_json=self.feature_cols_json,
            seg_sectors=json.loads(self.seg_sectors_json)
            if self.seg_sectors_json
            else None,
            seg_split_by=self.seg_split_by,
            seg_max_segments=self.seg_max_segments,
            seg_sector_overrides=json.loads(self.seg_sector_overrides_json)
            if self.seg_sector_overrides_json
            else None,
            is_segmented=self.is_segmented,
            workflow_run_id=self.workflow_run_id,
        )

    @property
    def is_segmented(self):
        return bool(self.seg_sectors_json)


class CalibrationRunLog(db.Model):
    __tablename__ = "calibration_run_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(
        db.String(64),
        db.ForeignKey("calibration_runs.run_id"),
        nullable=False,
        index=True,
    )
    logged_at = db.Column(db.DateTime, nullable=False)
    level = db.Column(
        db.String(16), nullable=False, default="info"
    )  # info | warn | error
    message = db.Column(db.String(1024), nullable=False)

    def to_dict(self):
        return dict(
            t=self.logged_at.strftime("%H:%M:%S") if self.logged_at else None,
            level=self.level,
            message=self.message,
        )


class CalibrationRunSegment(db.Model):
    __tablename__ = "calibration_run_segments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    calibration_run_id = db.Column(
        db.Integer,
        db.ForeignKey("calibration_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_key = db.Column(db.String(256), nullable=False)  # "{sector}__{split_value}"
    sector = db.Column(db.String(128), nullable=False)
    split_by = db.Column(db.String(16), nullable=False)  # 'subsector' | 'country'
    split_value = db.Column(db.String(128), nullable=False)  # actual value or "Others"
    model_config_id = db.Column(
        db.Integer, db.ForeignKey("model_configs.id"), nullable=True
    )
    row_count = db.Column(db.Integer, nullable=True)
    ead_total = db.Column(db.Float, nullable=True)
    artifact_path = db.Column(db.String(1024), nullable=True)
    train_metrics_json = db.Column(db.Text, nullable=True)
    val_metrics_json = db.Column(db.Text, nullable=True)
    status = db.Column(
        db.String(32), nullable=False, default="pending"
    )  # success|failed|skipped|queued|running
    error_message = db.Column(db.Text, nullable=True)
    hyperparams_json = db.Column(
        db.Text, nullable=True
    )  # per-segment override, if customized

    def to_dict(self):
        return dict(
            id=self.id,
            calibration_run_id=self.calibration_run_id,
            segment_key=self.segment_key,
            sector=self.sector,
            split_by=self.split_by,
            split_value=self.split_value,
            model_config_id=self.model_config_id,
            row_count=self.row_count,
            ead_total=self.ead_total,
            artifact_path=self.artifact_path,
            train_metrics=json.loads(self.train_metrics_json)
            if self.train_metrics_json
            else None,
            val_metrics=json.loads(self.val_metrics_json)
            if self.val_metrics_json
            else None,
            status=self.status,
            error_message=self.error_message,
            hyperparams=json.loads(self.hyperparams_json)
            if self.hyperparams_json
            else None,
        )


class Forecast(db.Model):
    __tablename__ = "forecasts"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    calibration_run_id = db.Column(
        db.Integer, db.ForeignKey("calibration_runs.id"), nullable=False
    )
    forecast_horizon = db.Column(db.Integer, nullable=True)
    forecast_json = db.Column(db.Text, nullable=True)  # legacy; NULL for new rows
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.now(timezone.utc)
    )

    results = db.relationship(
        "ForecastResult", cascade="all, delete-orphan", lazy="dynamic"
    )

    def to_dict(self):
        return dict(
            id=self.id,
            calibration_run_id=self.calibration_run_id,
            forecast_horizon=self.forecast_horizon,
            has_results=self.results.count() > 0,
            has_legacy_json=self.forecast_json is not None,
            created_at=self.created_at.isoformat() if self.created_at else None,
        )


class ForecastResult(db.Model):
    __tablename__ = "forecast_results"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    forecast_id = db.Column(
        db.Integer, db.ForeignKey("forecasts.id"), nullable=False, index=True
    )
    actual = db.Column(db.Float, nullable=True)
    predicted = db.Column(db.Float, nullable=True)
    client_id = db.Column(db.String(64), nullable=True)
    date = db.Column(db.String(32), nullable=True)
    meta_json = db.Column(
        db.Text, nullable=True
    )  # JSON obj of non-client_id/date meta cols
