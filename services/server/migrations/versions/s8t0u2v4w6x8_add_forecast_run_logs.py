"""add forecast_run_logs table

Revision ID: s8t0u2v4w6x8
Revises: r6s8t0u2v4w6
Create Date: 2026-06-19

Adds a log table for forecast runs so the run detail view can show
step-by-step progress messages, mirroring credit_risk_run_logs.
"""

import sqlalchemy as sa
from alembic import op

revision = "s8t0u2v4w6x8"
down_revision = "r6s8t0u2v4w6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forecast_run_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), nullable=False, index=True),
        sa.Column("t", sa.String(32), nullable=True),
        sa.Column("level", sa.String(16), nullable=False, default="info"),
        sa.Column("message", sa.Text, nullable=False),
    )


def downgrade():
    op.drop_table("forecast_run_logs")
