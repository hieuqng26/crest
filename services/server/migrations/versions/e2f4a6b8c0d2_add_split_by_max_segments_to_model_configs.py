"""add split_by/max_segments to model_configs

Revision ID: e2f4a6b8c0d2
Revises: d0e2f4a6b8c0
Create Date: 2026-07-05
"""

import sqlalchemy as sa
from alembic import op

revision = "e2f4a6b8c0d2"
down_revision = "d0e2f4a6b8c0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "model_configs",
        sa.Column(
            "split_by", sa.String(length=32), nullable=False, server_default="subsector"
        ),
    )
    op.add_column(
        "model_configs",
        sa.Column(
            "max_segments", sa.Integer(), nullable=False, server_default="5"
        ),
    )


def downgrade():
    op.drop_column("model_configs", "max_segments")
    op.drop_column("model_configs", "split_by")
