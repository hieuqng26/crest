"""add credit risk active and multi-cal columns

Revision ID: l7m9n1o3p5q7
Revises: k6l8m0n2o4p6
Create Date: 2026-06-17

"""

import sqlalchemy as sa
from alembic import op

revision = "l7m9n1o3p5q7"
down_revision = "k6l8m0n2o4p6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "credit_risk_runs",
        sa.Column("cal_run_ids_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "credit_risk_runs",
        sa.Column("target_cols_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "credit_risk_runs",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column("credit_risk_runs", "is_active")
    op.drop_column("credit_risk_runs", "target_cols_json")
    op.drop_column("credit_risk_runs", "cal_run_ids_json")
