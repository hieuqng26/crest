"""add search_config_json to model_configs and best_params_json to calibration_runs

Revision ID: e5f7c9d1b3a6
Revises: d4e6a8b2c1f3
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f7c9d1b3a6'
down_revision = 'd4e6a8b2c1f3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('model_configs',
        sa.Column('search_config_json', sa.Text(), nullable=True))
    op.add_column('calibration_runs',
        sa.Column('best_params_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('model_configs', 'search_config_json')
    op.drop_column('calibration_runs', 'best_params_json')
