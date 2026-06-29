"""add segmentation_configs and calibration_run_segments

Revision ID: t0u2v4w6x8y0
Revises: s8t0u2v4w6x8
Create Date: 2026-06-29

Adds SegmentationConfig table, CalibrationRunSegment table, and
segmentation_config_id FK column on calibration_runs.
"""

import sqlalchemy as sa
from alembic import op

revision = "t0u2v4w6x8y0"
down_revision = "s8t0u2v4w6x8"
branch_labels = None
depends_on = None


def upgrade():
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

    op.create_table(
        "calibration_run_segments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("calibration_run_id", sa.Integer(), nullable=False),
        sa.Column("segment_key", sa.String(256), nullable=False),
        sa.Column("sector", sa.String(128), nullable=False),
        sa.Column("split_by", sa.String(16), nullable=False),
        sa.Column("split_value", sa.String(128), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("ead_total", sa.Float(), nullable=True),
        sa.Column("artifact_path", sa.String(1024), nullable=True),
        sa.Column("train_metrics_json", sa.Text(), nullable=True),
        sa.Column("val_metrics_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["calibration_run_id"],
            ["calibration_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_calibration_run_segments_calibration_run_id",
        "calibration_run_segments",
        ["calibration_run_id"],
    )


def downgrade():
    op.drop_index(
        "ix_calibration_run_segments_calibration_run_id",
        table_name="calibration_run_segments",
    )
    op.drop_table("calibration_run_segments")
    op.drop_constraint(
        "fk_calibration_runs_segmentation_config",
        "calibration_runs",
        type_="foreignkey",
    )
    op.drop_column("calibration_runs", "segmentation_config_id")
    op.drop_table("segmentation_configs")
