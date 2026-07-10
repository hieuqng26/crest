import json
from datetime import datetime, timezone

from project import db


class WorkflowRun(db.Model):
    """Groups a multi-target train -> forecast -> credit-analysis pipeline
    launched from a single New Model submission. Child CalibrationRun /
    ForecastRun / CreditRiskRun rows reference this via workflow_run_id.
    """

    __tablename__ = "workflow_runs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    status = db.Column(
        db.String(32), nullable=False, default="queued"
    )  # queued|running|success|failed|deleting
    current_stage = db.Column(
        db.String(16), nullable=False, default="training"
    )  # training|forecast|analysis|done
    triggered_by = db.Column(
        db.String(64), db.ForeignKey("users.email"), nullable=False
    )
    # How the workflow was launched: 'manual' (New Model wizard / HTTP) or
    # 'auto' (MCP). Surfaced as the AUTO/MANUAL tag in job history.
    origin = db.Column(
        db.String(16), nullable=False, server_default="manual", default="manual"
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    analysis_skipped_reason = db.Column(db.String(512), nullable=True)

    # Snapshot of the "latest per kind" datasets resolved at launch time, for
    # audit/reproducibility — a later upload must not silently change what an
    # already-running workflow scores against.
    calibration_dataset_id = db.Column(
        db.Integer, db.ForeignKey("datasets.id"), nullable=False
    )
    forecast_dataset_id = db.Column(
        db.Integer, db.ForeignKey("datasets.id"), nullable=False
    )
    credit_dataset_id = db.Column(
        db.Integer, db.ForeignKey("datasets.id"), nullable=True
    )
    financial_dataset_id = db.Column(
        db.Integer, db.ForeignKey("datasets.id"), nullable=True
    )

    targets_json = db.Column(db.Text, nullable=True)  # requested targets + overrides
    analysis_params_json = db.Column(
        db.Text, nullable=True
    )  # {exposure, discount_rate, lifetime_horizon, curve}

    def to_dict(self):
        return dict(
            id=self.id,
            run_id=self.run_id,
            name=self.name,
            status=self.status,
            current_stage=self.current_stage,
            triggered_by=self.triggered_by,
            origin=self.origin,
            created_at=self.created_at.isoformat() if self.created_at else None,
            started_at=self.started_at.isoformat() if self.started_at else None,
            finished_at=self.finished_at.isoformat() if self.finished_at else None,
            error_message=self.error_message,
            analysis_skipped_reason=self.analysis_skipped_reason,
            calibration_dataset_id=self.calibration_dataset_id,
            forecast_dataset_id=self.forecast_dataset_id,
            credit_dataset_id=self.credit_dataset_id,
            financial_dataset_id=self.financial_dataset_id,
            targets=json.loads(self.targets_json) if self.targets_json else None,
            analysis_params=json.loads(self.analysis_params_json)
            if self.analysis_params_json
            else None,
        )
