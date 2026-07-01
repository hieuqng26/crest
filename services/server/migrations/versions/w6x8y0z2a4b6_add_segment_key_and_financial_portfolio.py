"""add segment_key to forecast_runs and financial_portfolio_dataset_id to credit_risk_runs

Revision ID: w6x8y0z2a4b6
Revises: v4w6x8y0z2a4
Create Date: 2026-06-30
"""

import sqlalchemy as sa
from alembic import op

revision = "w6x8y0z2a4b6"
down_revision = "v4w6x8y0z2a4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "forecast_runs",
        sa.Column("segment_key", sa.String(128), nullable=True),
    )
    op.add_column(
        "credit_risk_runs",
        sa.Column("financial_portfolio_dataset_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_crr_financial_portfolio_dataset",
        "credit_risk_runs",
        "datasets",
        ["financial_portfolio_dataset_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint(
        "fk_crr_financial_portfolio_dataset", "credit_risk_runs", type_="foreignkey"
    )
    op.drop_column("credit_risk_runs", "financial_portfolio_dataset_id")
    op.drop_column("forecast_runs", "segment_key")
