"""add performance indexes for list sorting, FK lookups and sector filtering

Revision ID: z2a4b6c8d0e2
Revises: j2k4l6m8n0p2
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "z2a4b6c8d0e2"
down_revision = "j2k4l6m8n0p2"
branch_labels = None
depends_on = None

# (index_name, table, [columns]). Names match SQLAlchemy's own convention for the
# `index=True` / __table_args__ declarations now on these models, so an environment
# that already materialised them via create_all() won't collide with this migration.
_INDEXES = [
    ("ix_forecasts_calibration_run_id", "forecasts", ["calibration_run_id"]),
    ("ix_calibration_runs_started_at", "calibration_runs", ["started_at"]),
    ("ix_forecast_runs_created_at", "forecast_runs", ["created_at"]),
    ("ix_credit_risk_runs_created_at", "credit_risk_runs", ["created_at"]),
    ("ix_workflow_runs_created_at", "workflow_runs", ["created_at"]),
    ("ix_crs_run_sector", "calibration_run_segments", ["calibration_run_id", "sector"]),
]


def _existing_indexes(table):
    insp = sa.inspect(op.get_bind())
    return {ix["name"] for ix in insp.get_indexes(table)}


def upgrade():
    for name, table, cols in _INDEXES:
        if name not in _existing_indexes(table):
            op.create_index(name, table, cols)


def downgrade():
    for name, table, _cols in reversed(_INDEXES):
        if name in _existing_indexes(table):
            op.drop_index(name, table_name=table)
