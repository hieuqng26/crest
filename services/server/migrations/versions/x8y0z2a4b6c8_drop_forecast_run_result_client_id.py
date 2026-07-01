"""drop client_id from forecast_run_results

Revision ID: x8y0z2a4b6c8
Revises: w6x8y0z2a4b6
Create Date: 2026-07-01

Forecast datasets are MEV-only (no client_id) — a forecast run scores every
trained segment (or the single model) against the whole scenario table, and
results are routed to clients by segment during credit risk analysis, not by
a per-row client_id.
"""

import sqlalchemy as sa
from alembic import op

revision = "x8y0z2a4b6c8"
down_revision = "w6x8y0z2a4b6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("forecast_run_results") as batch_op:
        batch_op.drop_column("client_id")


def downgrade():
    with op.batch_alter_table("forecast_run_results") as batch_op:
        batch_op.add_column(sa.Column("client_id", sa.String(64), nullable=True))
