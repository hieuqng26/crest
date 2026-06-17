"""add credit risk runs and results

Revision ID: k6l8m0n2o4p6
Revises: j5k7l9m1n3o5
Create Date: 2026-06-17
"""

import sqlalchemy as sa
from alembic import op

revision = "k6l8m0n2o4p6"
down_revision = "j5k7l9m1n3o5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "credit_risk_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("cal_run_id", sa.String(64), nullable=True),
        sa.Column("exposure", sa.Float(), nullable=False),
        sa.Column("discount_rate", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("lifetime_horizon", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("curve", sa.String(32), nullable=False, server_default="moodys"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("triggered_by", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_table(
        "credit_risk_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("kmv_json", sa.Text(), nullable=True),
        sa.Column("ecl_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["credit_risk_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_risk_results_run_id", "credit_risk_results", ["run_id"])
    op.create_index("ix_credit_risk_results_client_id", "credit_risk_results", ["client_id"])


def downgrade():
    op.drop_index("ix_credit_risk_results_client_id", table_name="credit_risk_results")
    op.drop_index("ix_credit_risk_results_run_id", table_name="credit_risk_results")
    op.drop_table("credit_risk_results")
    op.drop_table("credit_risk_runs")
