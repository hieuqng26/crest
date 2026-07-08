"""add segment tagging to forecast_run_results and credit_risk_results

Revision ID: i0j2k4l6m8n0
Revises: h8i0j2k4l6m8
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "i0j2k4l6m8n0"
down_revision = "h8i0j2k4l6m8"
branch_labels = None
depends_on = None


def upgrade():
    # forecast_run_results: denormalised segment_key for in-place per-segment re-score
    op.add_column(
        "forecast_run_results",
        sa.Column("segment_key", sa.String(length=256), nullable=True),
    )
    op.create_index(
        "ix_forecast_run_results_run_segment",
        "forecast_run_results",
        ["forecast_run_id", "segment_key"],
    )

    # credit_risk_results: denormalised client segmentation for per-segment recompute + filters
    op.add_column(
        "credit_risk_results",
        sa.Column("sector", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "credit_risk_results",
        sa.Column("subsector", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "credit_risk_results",
        sa.Column("country", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "credit_risk_results",
        sa.Column("segment_key", sa.String(length=256), nullable=True),
    )
    op.create_index(
        "ix_credit_risk_results_run_segment",
        "credit_risk_results",
        ["run_id", "segment_key"],
    )


def downgrade():
    op.drop_index(
        "ix_credit_risk_results_run_segment", table_name="credit_risk_results"
    )
    op.drop_column("credit_risk_results", "segment_key")
    op.drop_column("credit_risk_results", "country")
    op.drop_column("credit_risk_results", "subsector")
    op.drop_column("credit_risk_results", "sector")

    op.drop_index(
        "ix_forecast_run_results_run_segment", table_name="forecast_run_results"
    )
    op.drop_column("forecast_run_results", "segment_key")
