"""add credit_risk_run_cal_inputs junction table

Revision ID: q4r6s8t0u2v4
Revises: p2q4r6s8t0u2
Create Date: 2026-06-18

Replaces the cal_run_ids_json TEXT blob on credit_risk_runs with a proper
junction table that carries FK constraints:
  - credit_risk_run_id ON DELETE CASCADE  (junction rows disappear with the CR run)
  - calibration_run_id (no ON DELETE)     (blocks deletion of a cal run while it is
                                           still referenced by a credit risk run)

Existing data is migrated from cal_run_ids_json where the value is a JSON dict
{slot: cal_run_uuid}. Rows with a legacy JSON array (pre-dict format) are skipped —
they have no slot information and cannot be reconstructed.
"""

import json

import sqlalchemy as sa
from alembic import op
from collections import defaultdict

revision = "q4r6s8t0u2v4"
down_revision = "p2q4r6s8t0u2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "credit_risk_run_cal_inputs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "credit_risk_run_id",
            sa.Integer,
            sa.ForeignKey("credit_risk_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "calibration_run_id",
            sa.Integer,
            sa.ForeignKey("calibration_runs.id"),
            nullable=False,
        ),
        sa.Column("cal_run_uuid", sa.String(64), nullable=False),
        sa.Column("slot", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_credit_risk_run_cal_inputs_cr_run_id",
        "credit_risk_run_cal_inputs",
        ["credit_risk_run_id"],
    )

    # Migrate data from cal_run_ids_json
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, cal_run_ids_json FROM credit_risk_runs"
            " WHERE cal_run_ids_json IS NOT NULL"
        )
    ).fetchall()
    for row in rows:
        try:
            data = json.loads(row.cal_run_ids_json or "{}")
            if not isinstance(data, dict):
                continue
            for slot, uuid in data.items():
                if not uuid or not isinstance(uuid, str):
                    continue
                cal_run = conn.execute(
                    sa.text("SELECT id FROM calibration_runs WHERE run_id = :run_id"),
                    {"run_id": uuid},
                ).first()
                if cal_run:
                    conn.execute(
                        sa.text(
                            "INSERT INTO credit_risk_run_cal_inputs"
                            " (credit_risk_run_id, calibration_run_id, cal_run_uuid, slot)"
                            " VALUES (:cr_id, :cal_id, :uuid, :slot)"
                        ),
                        {"cr_id": row.id, "cal_id": cal_run.id, "uuid": uuid, "slot": slot},
                    )
        except Exception:
            pass

    with op.batch_alter_table("credit_risk_runs") as batch_op:
        batch_op.drop_column("cal_run_ids_json")


def downgrade():
    with op.batch_alter_table("credit_risk_runs") as batch_op:
        batch_op.add_column(sa.Column("cal_run_ids_json", sa.Text, nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT credit_risk_run_id, slot, cal_run_uuid"
            " FROM credit_risk_run_cal_inputs"
        )
    ).fetchall()
    by_run: dict = defaultdict(dict)
    for row in rows:
        by_run[row.credit_risk_run_id][row.slot] = row.cal_run_uuid
    for cr_id, inputs in by_run.items():
        conn.execute(
            sa.text(
                "UPDATE credit_risk_runs SET cal_run_ids_json = :data WHERE id = :id"
            ),
            {"data": json.dumps(inputs), "id": cr_id},
        )

    op.drop_index(
        "ix_credit_risk_run_cal_inputs_cr_run_id",
        table_name="credit_risk_run_cal_inputs",
    )
    op.drop_table("credit_risk_run_cal_inputs")
