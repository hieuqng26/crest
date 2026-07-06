"""add name to calibration_runs

Revision ID: f4a6b8c0d2e4
Revises: e2f4a6b8c0d2
Create Date: 2026-07-05
"""

import sqlalchemy as sa
from alembic import op

revision = "f4a6b8c0d2e4"
down_revision = "e2f4a6b8c0d2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "calibration_runs", sa.Column("name", sa.String(length=255), nullable=True)
    )


def downgrade():
    op.drop_column("calibration_runs", "name")
