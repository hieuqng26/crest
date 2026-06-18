"""drop dead columns from credit_risk_runs

Revision ID: o0p2q4r6s8t0
Revises: n9o1p3q5r7s9
Create Date: 2026-06-18

- target_cols_json: always NULL since the dict-based cal_inputs redesign
- cal_run_id (singular): orphaned column from the initial credit_risk_runs
  migration; replaced by cal_run_ids_json in the very next migration and
  never mapped in the ORM
"""

from alembic import op
import sqlalchemy as sa

revision = "o0p2q4r6s8t0"
down_revision = "n9o1p3q5r7s9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("credit_risk_runs") as batch_op:
        batch_op.drop_column("target_cols_json")
        batch_op.drop_column("cal_run_id")


def downgrade():
    with op.batch_alter_table("credit_risk_runs") as batch_op:
        batch_op.add_column(sa.Column("cal_run_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("target_cols_json", sa.Text(), nullable=True))
