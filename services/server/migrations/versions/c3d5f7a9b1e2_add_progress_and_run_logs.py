"""Add progress fields to calibration_runs and calibration_run_logs table.

Revision ID: c3d5f7a9b1e2
Revises: b2c4e8f1a3d5
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d5f7a9b1e2'
down_revision = 'b2c4e8f1a3d5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('calibration_runs', sa.Column('progress', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('calibration_runs', sa.Column('progress_message', sa.String(length=512), nullable=True))

    op.create_table(
        'calibration_run_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('logged_at', sa.DateTime(), nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False, server_default='info'),
        sa.Column('message', sa.String(length=1024), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['calibration_runs.run_id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_calibration_run_logs_run_id', 'calibration_run_logs', ['run_id'])


def downgrade():
    op.drop_index('ix_calibration_run_logs_run_id', table_name='calibration_run_logs')
    op.drop_table('calibration_run_logs')
    op.drop_column('calibration_runs', 'progress_message')
    op.drop_column('calibration_runs', 'progress')
