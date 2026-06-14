"""drop mlflow_run_id from calibration_runs

Revision ID: d4e6a8b2c1f3
Revises: c3d5f7a9b1e2
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e6a8b2c1f3'
down_revision = 'c3d5f7a9b1e2'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('calibration_runs', 'mlflow_run_id')


def downgrade():
    op.add_column('calibration_runs',
        sa.Column('mlflow_run_id', sa.String(length=128), nullable=True))
