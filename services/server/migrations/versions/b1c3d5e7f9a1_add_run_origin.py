"""add origin (manual|auto) to run + workflow tables

Revision ID: b1c3d5e7f9a1
Revises: f6a8b0c2d4e6
Create Date: 2026-07-10

Records how a run/workflow was launched so job history can tag it AUTO
(MCP / New Model "Auto" mode) vs MANUAL (New Model wizard / HTTP). Added to
``workflow_runs`` and the three standalone-launchable ``*_runs`` tables.

``server_default='manual'`` makes the column NOT NULL safe to add to tables
that already hold rows (existing rows become 'manual', the human default). New
rows get their origin from the launching transport (HTTP=manual, MCP=auto).
"""

import sqlalchemy as sa
from alembic import op

revision = "b1c3d5e7f9a1"
down_revision = "f6a8b0c2d4e6"
branch_labels = None
depends_on = None

_TABLES = (
    "workflow_runs",
    "calibration_runs",
    "forecast_runs",
    "credit_risk_runs",
)


def upgrade():
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "origin",
                sa.String(16),
                nullable=False,
                server_default="manual",
            ),
        )


def downgrade():
    for table in _TABLES:
        op.drop_column(table, "origin")
