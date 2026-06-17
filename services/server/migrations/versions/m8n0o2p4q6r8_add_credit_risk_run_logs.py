"""add credit_risk_run_logs table

Revision ID: m8n0o2p4q6r8
Revises: l7m9n1o3p5q7
Create Date: 2026-06-17

"""

import sqlalchemy as sa
from alembic import op

revision = "m8n0o2p4q6r8"
down_revision = "l7m9n1o3p5q7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "credit_risk_run_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("t", sa.String(32), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["credit_risk_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_risk_run_logs_run_id", "credit_risk_run_logs", ["run_id"])


def downgrade():
    op.drop_index("ix_credit_risk_run_logs_run_id", table_name="credit_risk_run_logs")
    op.drop_table("credit_risk_run_logs")
