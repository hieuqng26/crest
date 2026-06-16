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
    feature_cols_json = db.Column(db.Text, nullable=True)
    target_col = db.Column(db.String(255), nullable=True)
    train_split = db.Column(db.Float, nullable=False, default=0.8)
    scaler = db.Column(db.String(32), nullable=True)
    search_config_json = db.Column(db.Text, nullable=True)
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
            feature_cols_json=self.feature_cols_json,
            target_col=self.target_col,
            train_split=self.train_split,
            scaler=self.scaler,
            search_config_json=self.search_config_json,
            created_by=self.created_by,
            created_at=self.created_at.isoformat() if self.created_at else None,
        )


class CalibrationRun(db.Model):
    __tablename__ = "calibration_runs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(db.String(64), unique=True, nullable=False)
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
    secondary_dataset_ids_json = db.Column(db.Text, nullable=True)  # JSON list of int IDs
    merge_steps_json = db.Column(db.Text, nullable=True)  # JSON list of {type, on}

    forecasts = db.relationship(
        "Forecast", backref="calibration_run", cascade="all, delete", lazy=True
    )
    logs = db.relationship(
        "CalibrationRunLog", backref="calibration_run", cascade="all, delete", lazy=True
    )

    def to_dict(self):
        return dict(
            id=self.id,
            run_id=self.run_id,
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
        )


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


class Forecast(db.Model):
    __tablename__ = "forecasts"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    calibration_run_id = db.Column(
        db.Integer, db.ForeignKey("calibration_runs.id"), nullable=False
    )
    forecast_horizon = db.Column(db.Integer, nullable=True)
    forecast_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.now(timezone.utc)
    )

    def to_dict(self):
        return dict(
            id=self.id,
            calibration_run_id=self.calibration_run_id,
            forecast_horizon=self.forecast_horizon,
            forecast_json=self.forecast_json,
            created_at=self.created_at.isoformat() if self.created_at else None,
        )
