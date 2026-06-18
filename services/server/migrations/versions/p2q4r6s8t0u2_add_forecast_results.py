"""add forecast_results table

Revision ID: p2q4r6s8t0u2
Revises: o0p2q4r6s8t0
Create Date: 2026-06-18

Normalises forecast data out of the forecast_json TEXT blob into a proper
table so the credit risk task can query only the columns it needs instead of
deserialising the entire blob in Python.
"""

import sqlalchemy as sa
from alembic import op

revision = "p2q4r6s8t0u2"
down_revision = "o0p2q4r6s8t0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forecast_results",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "forecast_id",
            sa.Integer,
            sa.ForeignKey("forecasts.id"),
            nullable=False,
        ),
        sa.Column("actual", sa.Float, nullable=True),
        sa.Column("predicted", sa.Float, nullable=True),
        sa.Column("client_id", sa.String(64), nullable=True),
        sa.Column("date", sa.String(32), nullable=True),
        sa.Column("meta_json", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_forecast_results_forecast_id", "forecast_results", ["forecast_id"]
    )


def downgrade():
    op.drop_index("ix_forecast_results_forecast_id", table_name="forecast_results")
    op.drop_table("forecast_results")
