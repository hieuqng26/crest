"""add seg_sector_overrides_json to calibration_runs, model_config_id to calibration_run_segments

Revision ID: y0z2a4b6c8d0
Revises: x8y0z2a4b6c8
Create Date: 2026-07-01
"""

import sqlalchemy as sa
from alembic import op

revision = "y0z2a4b6c8d0"
down_revision = "x8y0z2a4b6c8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "calibration_runs",
        sa.Column("seg_sector_overrides_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "calibration_run_segments",
        sa.Column("model_config_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_crs_model_config",
        "calibration_run_segments",
        "model_configs",
        ["model_config_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint(
        "fk_crs_model_config", "calibration_run_segments", type_="foreignkey"
    )
    op.drop_column("calibration_run_segments", "model_config_id")
    op.drop_column("calibration_runs", "seg_sector_overrides_json")
