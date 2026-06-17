"""drop target_col and feature_cols_json from model_configs

Revision ID: n9o1p3q5r7s9
Revises: m8n0o2p4q6r8
Create Date: 2026-06-17

"""

import sqlalchemy as sa
from alembic import op

revision = "n9o1p3q5r7s9"
down_revision = "m8n0o2p4q6r8"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("model_configs", "target_col")
    op.drop_column("model_configs", "feature_cols_json")


def downgrade():
    op.add_column("model_configs", sa.Column("target_col", sa.String(255), nullable=True))
    op.add_column("model_configs", sa.Column("feature_cols_json", sa.Text(), nullable=True))
