"""add credit_risk_analysis_series (materialised heatmap/forecast level series)

Revision ID: j2k4l6m8n0p2
Revises: i0j2k4l6m8n0
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "j2k4l6m8n0p2"
down_revision = "i0j2k4l6m8n0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "credit_risk_analysis_series",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("credit_risk_run_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("sector", sa.String(length=128), nullable=True),
        sa.Column("slot", sa.String(length=32), nullable=False),
        sa.Column("scenario", sa.String(length=32), nullable=False),
        sa.Column(
            "is_history", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["credit_risk_run_id"],
            ["credit_risk_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_credit_risk_analysis_series_credit_risk_run_id",
        "credit_risk_analysis_series",
        ["credit_risk_run_id"],
    )
    op.create_index(
        "ix_cr_analysis_series_lookup",
        "credit_risk_analysis_series",
        ["credit_risk_run_id", "scope_type", "scope_key"],
    )


def downgrade():
    op.drop_index(
        "ix_cr_analysis_series_lookup",
        table_name="credit_risk_analysis_series",
    )
    op.drop_index(
        "ix_credit_risk_analysis_series_credit_risk_run_id",
        table_name="credit_risk_analysis_series",
    )
    op.drop_table("credit_risk_analysis_series")
