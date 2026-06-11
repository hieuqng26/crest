"""Add datasets, model_configs, calibration_runs, forecasts tables.

Revision ID: b2c4e8f1a3d5
Revises: a19c71d70fa4
Create Date: 2026-06-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c4e8f1a3d5'
down_revision = 'a19c71d70fa4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'datasets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('file_path', sa.String(length=1024), nullable=True),
        sa.Column('schema_json', sa.Text(), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.email']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'model_configs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('family', sa.String(length=32), nullable=False),
        sa.Column('algorithm', sa.String(length=128), nullable=False),
        sa.Column('hyperparams_json', sa.Text(), nullable=True),
        sa.Column('feature_cols_json', sa.Text(), nullable=True),
        sa.Column('target_col', sa.String(length=255), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.email']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'calibration_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('model_config_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('triggered_by', sa.String(length=64), nullable=False),
        sa.Column('mlflow_run_id', sa.String(length=128), nullable=True),
        sa.Column('artifact_path', sa.String(length=1024), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('train_metrics_json', sa.Text(), nullable=True),
        sa.Column('val_metrics_json', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id']),
        sa.ForeignKeyConstraint(['model_config_id'], ['model_configs.id']),
        sa.ForeignKeyConstraint(['triggered_by'], ['users.email']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id'),
    )
    op.create_table(
        'forecasts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('calibration_run_id', sa.Integer(), nullable=False),
        sa.Column('forecast_horizon', sa.Integer(), nullable=True),
        sa.Column('forecast_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['calibration_run_id'], ['calibration_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('forecasts')
    op.drop_table('calibration_runs')
    op.drop_table('model_configs')
    op.drop_table('datasets')
