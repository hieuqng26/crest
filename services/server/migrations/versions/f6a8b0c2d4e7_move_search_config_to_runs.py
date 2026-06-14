"""move search_config_json from model_configs to calibration_runs

Revision ID: f6a8b0c2d4e7
Revises: e5f7c9d1b3a6
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a8b0c2d4e7'
down_revision = 'e5f7c9d1b3a6'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('model_configs', 'search_config_json')
    op.add_column('calibration_runs',
        sa.Column('search_config_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('calibration_runs', 'search_config_json')
    op.add_column('model_configs',
        sa.Column('search_config_json', sa.Text(), nullable=True))
