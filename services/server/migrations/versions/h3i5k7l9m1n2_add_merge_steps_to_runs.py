"""add merge_steps and secondary_dataset_ids to calibration_runs

Revision ID: h3i5k7l9m1n2
Revises: g2h4i6j8k0l2
Create Date: 2026-06-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "h3i5k7l9m1n2"
down_revision = "g2h4i6j8k0l2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "calibration_runs",
        sa.Column("secondary_dataset_ids_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "calibration_runs",
        sa.Column("merge_steps_json", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("calibration_runs", "merge_steps_json")
    op.drop_column("calibration_runs", "secondary_dataset_ids_json")
