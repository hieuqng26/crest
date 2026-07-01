from datetime import datetime, timezone

from project import db


class PdRating(db.Model):
    __tablename__ = "pd_ratings"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    curve_name = db.Column(db.String(32), nullable=False, default="moodys")
    category = db.Column(db.Integer, nullable=False)
    rating = db.Column(db.String(16), nullable=False)
    pd = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return dict(
            id=self.id,
            curve_name=self.curve_name,
            category=self.category,
            rating=self.rating,
            pd=self.pd,
        )


class CreditRiskForecastInput(db.Model):
    __tablename__ = "credit_risk_run_forecast_inputs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    credit_risk_run_id = db.Column(
        db.Integer,
        db.ForeignKey("credit_risk_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    forecast_run_id = db.Column(
        db.Integer,
        db.ForeignKey("forecast_runs.id"),
        nullable=False,
    )
    forecast_run_uuid = db.Column(db.String(64), nullable=False)
    slot = db.Column(db.String(32), nullable=False)


class CreditRiskRun(db.Model):
    __tablename__ = "credit_risk_runs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(db.String(64), unique=True, nullable=False)
    dataset_id = db.Column(db.Integer, db.ForeignKey("datasets.id"), nullable=False)
    financial_portfolio_dataset_id = db.Column(
        db.Integer, db.ForeignKey("datasets.id"), nullable=True
    )
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    exposure = db.Column(db.Float, nullable=False)
    discount_rate = db.Column(db.Float, nullable=False, default=0.05)
    lifetime_horizon = db.Column(db.Integer, nullable=False, default=5)
    curve = db.Column(db.String(32), nullable=False, default="moodys")
    status = db.Column(db.String(32), nullable=False, default="queued")
    triggered_by = db.Column(db.String(64), nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    progress = db.Column(db.Integer, default=0)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    forecast_inputs_rel = db.relationship(
        "CreditRiskForecastInput", cascade="all, delete-orphan", lazy=True
    )
    results = db.relationship(
        "CreditRiskResult", backref="run", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return dict(
            id=self.id,
            run_id=self.run_id,
            dataset_id=self.dataset_id,
            financial_portfolio_dataset_id=self.financial_portfolio_dataset_id,
            forecast_inputs={
                inp.slot: inp.forecast_run_uuid for inp in self.forecast_inputs_rel
            },
            is_active=bool(self.is_active),
            exposure=self.exposure,
            discount_rate=self.discount_rate,
            lifetime_horizon=self.lifetime_horizon,
            curve=self.curve,
            status=self.status,
            triggered_by=self.triggered_by,
            started_at=self.started_at.isoformat() if self.started_at else None,
            finished_at=self.finished_at.isoformat() if self.finished_at else None,
            error_message=self.error_message,
            progress=self.progress,
            created_at=self.created_at.isoformat() if self.created_at else None,
        )


class CreditRiskResult(db.Model):
    __tablename__ = "credit_risk_results"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(
        db.String(64),
        db.ForeignKey("credit_risk_runs.run_id"),
        nullable=False,
        index=True,
    )
    client_id = db.Column(db.String(64), nullable=False, index=True)
    kmv_json = db.Column(db.Text, nullable=True)
    ecl_json = db.Column(db.Text, nullable=True)


class CreditRiskRunLog(db.Model):
    __tablename__ = "credit_risk_run_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_id = db.Column(
        db.String(64),
        db.ForeignKey("credit_risk_runs.run_id"),
        nullable=False,
        index=True,
    )
    t = db.Column(db.String(32), nullable=False)
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
