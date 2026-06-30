"""inline segmentation settings on calibration_runs

Revision ID: v4w6x8y0z2a4
Revises: u2v4w6x8y0z2
Create Date: 2026-06-30

Drops the separate segmentation_configs table and segmentation_config_id FK.
Adds seg_sectors_json, seg_split_by, and seg_max_segments inline on calibration_runs.
"""

import sqlalchemy as sa
from alembic import op

revision = "v4w6x8y0z2a4"
down_revision = "u2v4w6x8y0z2"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "fk_calibration_runs_segmentation_config",
        "calibration_runs",
        type_="foreignkey",
    )
    op.drop_column("calibration_runs", "segmentation_config_id")
    op.drop_table("segmentation_configs")
    op.add_column(
        "calibration_runs",
        sa.Column("seg_sectors_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "calibration_runs",
        sa.Column("seg_split_by", sa.String(16), nullable=True),
    )
    op.add_column(
        "calibration_runs",
        sa.Column("seg_max_segments", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("calibration_runs", "seg_max_segments")
    op.drop_column("calibration_runs", "seg_split_by")
    op.drop_column("calibration_runs", "seg_sectors_json")
    op.create_table(
        "segmentation_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_split", sa.String(16), nullable=False),
        sa.Column("max_segments", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("sector_rules_json", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.email"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "calibration_runs",
        sa.Column("segmentation_config_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_calibration_runs_segmentation_config",
        "calibration_runs",
        "segmentation_configs",
        ["segmentation_config_id"],
        ["id"],
    )
