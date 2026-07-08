"""add sector/segment tags to run log tables for the unified workflow log view

Revision ID: a4b6c8d0e2f4
Revises: z2a4b6c8d0e2
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "a4b6c8d0e2f4"
down_revision = "z2a4b6c8d0e2"
branch_labels = None
depends_on = None

_TABLES = ("calibration_run_logs", "forecast_run_logs", "credit_risk_run_logs")
_COLUMNS = ("sector", "segment")


def _existing_columns(table):
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def upgrade():
    for table in _TABLES:
        have = _existing_columns(table)
        for col in _COLUMNS:
            if col not in have:
                op.add_column(table, sa.Column(col, sa.String(length=128), nullable=True))


def downgrade():
    for table in _TABLES:
        have = _existing_columns(table)
        for col in _COLUMNS:
            if col in have:
                op.drop_column(table, col)
