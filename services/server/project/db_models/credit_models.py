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
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    workflow_run_id = db.Column(
        db.Integer, db.ForeignKey("workflow_runs.id"), nullable=True, index=True
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
            workflow_run_id=self.workflow_run_id,
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
    # Denormalised client segmentation, resolved at compute time. Lets a single
    # segment's client rows be deleted/recomputed in place via an indexed WHERE
    # (see recompute_segment_downstream) and powers the Sector/Segment result filters.
    sector = db.Column(db.String(128), nullable=True)
    subsector = db.Column(db.String(128), nullable=True)
    country = db.Column(db.String(128), nullable=True)
    segment_key = db.Column(db.String(256), nullable=True)

    __table_args__ = (
        db.Index(
            "ix_credit_risk_results_run_segment",
            "run_id",
            "segment_key",
        ),
    )


class CreditRiskAnalysisSeries(db.Model):
    """Materialised level series for the Sector Heatmap & Financial Forecast pages.

    Both pages otherwise recompute the same aggregate on every request by
    downloading the portfolio from MinIO, parsing it with pandas, rebuilding the
    forecast index, and summing per sector/client. That work is done ONCE when the
    credit-analysis job finishes and stored here as plain rows, so page loads become
    cheap indexed SELECTs. Rows are immutable for a successful run and are deleted
    when the run is deleted or re-run (cascade via credit_risk_run_id).

    One row per (run, scope, slot, scenario, year). `is_history=True` rows carry the
    historical actuals series (scenario is stored as 'History'); forecast rows carry
    one of the run's scenarios (Baseline / Adverse / …).
    """

    __tablename__ = "credit_risk_analysis_series"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    credit_risk_run_id = db.Column(
        db.Integer,
        db.ForeignKey("credit_risk_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 'sector' → aggregate across a whole sector; 'client' → a single company.
    scope_type = db.Column(db.String(16), nullable=False)
    scope_key = db.Column(db.String(128), nullable=False)  # sector name or client_id
    # For client-scope rows, the owning sector (lets the heatmap drill-down filter
    # by sector without a join back to the portfolio).
    sector = db.Column(db.String(128), nullable=True)
    slot = db.Column(db.String(32), nullable=False)  # total_assets / total_revenue / …
    scenario = db.Column(db.String(32), nullable=False)  # 'History' or a scenario name
    is_history = db.Column(db.Boolean, nullable=False, default=False)
    year = db.Column(db.Integer, nullable=False)
    value = db.Column(db.Float, nullable=True)

    __table_args__ = (
        db.Index(
            "ix_cr_analysis_series_lookup",
            "credit_risk_run_id",
            "scope_type",
            "scope_key",
        ),
    )


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
    # Set only on segment-scoped lines (per-segment credit recompute), so the
    # unified workflow log view can filter by sector/segment. NULL on general lines.
    sector = db.Column(db.String(128), nullable=True)
    segment = db.Column(db.String(128), nullable=True)

    def to_dict(self):
        return dict(
            id=self.id,
            run_id=self.run_id,
            t=self.t,
            level=self.level,
            message=self.message,
            sector=self.sector,
            segment=self.segment,
        )
