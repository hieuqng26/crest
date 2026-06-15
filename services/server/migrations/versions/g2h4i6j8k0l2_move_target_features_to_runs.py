"""move target_col and feature_cols to calibration_runs

Revision ID: g2h4i6j8k0l2
Revises: a1b3c5d7e9f0
Create Date: 2026-06-15
"""
import sqlalchemy as sa
from alembic import op

revision = "g2h4i6j8k0l2"
down_revision = "a1b3c5d7e9f0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "calibration_runs", sa.Column("target_col", sa.String(255), nullable=True)
    )
    op.add_column(
        "calibration_runs", sa.Column("feature_cols_json", sa.Text(), nullable=True)
    )


def downgrade():
    op.drop_column("calibration_runs", "target_col")
    op.drop_column("calibration_runs", "feature_cols_json")
