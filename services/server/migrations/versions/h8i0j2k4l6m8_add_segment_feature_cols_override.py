"""add feature_cols_json override to calibration_run_segments

Revision ID: h8i0j2k4l6m8
Revises: g6h8i0j2k4l6
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "h8i0j2k4l6m8"
down_revision = "g6h8i0j2k4l6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "calibration_run_segments",
        sa.Column("feature_cols_json", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("calibration_run_segments", "feature_cols_json")
