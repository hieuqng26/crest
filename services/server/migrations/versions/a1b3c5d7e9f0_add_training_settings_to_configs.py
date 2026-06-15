"""add training settings to model_configs and calibration_runs

Revision ID: a1b3c5d7e9f0
Revises: f6a8b0c2d4e7
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b3c5d7e9f0"
down_revision = "f6a8b0c2d4e7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "model_configs",
        sa.Column("train_split", sa.Float(), nullable=False, server_default="0.8"),
    )
    op.add_column(
        "model_configs",
        sa.Column("scaler", sa.String(32), nullable=True),
    )
    op.add_column(
        "model_configs",
        sa.Column("search_config_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "calibration_runs",
        sa.Column("train_split", sa.Float(), nullable=False, server_default="0.8"),
    )
    op.add_column(
        "calibration_runs",
        sa.Column("scaler", sa.String(32), nullable=True),
    )


def downgrade():
    op.drop_column("model_configs", "train_split")
    op.drop_column("model_configs", "scaler")
    op.drop_column("model_configs", "search_config_json")
    op.drop_column("calibration_runs", "train_split")
    op.drop_column("calibration_runs", "scaler")
