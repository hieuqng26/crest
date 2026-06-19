"""add forecast_runs, forecast_run_results, credit_risk_run_forecast_inputs

Revision ID: r6s8t0u2v4w6
Revises: q4r6s8t0u2v4
Create Date: 2026-06-18

Introduces the standalone Forecast module:
  - forecast_runs: one row per user-launched forecast run (model + dataset → predictions)
  - forecast_run_results: per-row predictions from the forecast run
  - credit_risk_run_forecast_inputs: replaces credit_risk_run_cal_inputs;
    credit risk jobs now reference forecast runs instead of calibration runs

credit_risk_run_cal_inputs is dropped (no FK restores needed — added in q4r6s8t0u2v4
and not yet populated in production).
"""

import sqlalchemy as sa
from alembic import op

revision = "r6s8t0u2v4w6"
down_revision = "q4r6s8t0u2v4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column(
            "calibration_run_id",
            sa.Integer,
            sa.ForeignKey("calibration_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            sa.Integer,
            sa.ForeignKey("datasets.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("triggered_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "forecast_run_results",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "forecast_run_id",
            sa.Integer,
            sa.ForeignKey("forecast_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(64), nullable=True),
        sa.Column("date", sa.String(32), nullable=True),
        sa.Column("predicted", sa.Float, nullable=True),
        sa.Column("meta_json", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_forecast_run_results_forecast_run_id",
        "forecast_run_results",
        ["forecast_run_id"],
    )

    op.create_table(
        "credit_risk_run_forecast_inputs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "credit_risk_run_id",
            sa.Integer,
            sa.ForeignKey("credit_risk_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "forecast_run_id",
            sa.Integer,
            sa.ForeignKey("forecast_runs.id"),
            nullable=False,
        ),
        sa.Column("forecast_run_uuid", sa.String(64), nullable=False),
        sa.Column("slot", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_credit_risk_run_forecast_inputs_cr_run_id",
        "credit_risk_run_forecast_inputs",
        ["credit_risk_run_id"],
    )

    op.drop_index(
        "ix_credit_risk_run_cal_inputs_cr_run_id",
        table_name="credit_risk_run_cal_inputs",
    )
    op.drop_table("credit_risk_run_cal_inputs")


def downgrade():
    op.create_table(
        "credit_risk_run_cal_inputs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "credit_risk_run_id",
            sa.Integer,
            sa.ForeignKey("credit_risk_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "calibration_run_id",
            sa.Integer,
            sa.ForeignKey("calibration_runs.id"),
            nullable=False,
        ),
        sa.Column("cal_run_uuid", sa.String(64), nullable=False),
        sa.Column("slot", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_credit_risk_run_cal_inputs_cr_run_id",
        "credit_risk_run_cal_inputs",
        ["credit_risk_run_id"],
    )

    op.drop_index(
        "ix_credit_risk_run_forecast_inputs_cr_run_id",
        table_name="credit_risk_run_forecast_inputs",
    )
    op.drop_table("credit_risk_run_forecast_inputs")
    op.drop_index(
        "ix_forecast_run_results_forecast_run_id",
        table_name="forecast_run_results",
    )
    op.drop_table("forecast_run_results")
    op.drop_table("forecast_runs")
