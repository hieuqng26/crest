"""add hyperparams_json override to calibration_run_segments

Revision ID: d0e2f4a6b8c0
Revises: y0z2a4b6c8d0
Create Date: 2026-07-04
"""

import sqlalchemy as sa
from alembic import op

revision = "d0e2f4a6b8c0"
down_revision = "y0z2a4b6c8d0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "calibration_run_segments",
        sa.Column("hyperparams_json", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("calibration_run_segments", "hyperparams_json")
