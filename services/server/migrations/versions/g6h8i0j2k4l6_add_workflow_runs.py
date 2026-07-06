"""add workflow_runs table + workflow_run_id FKs + financial_portfolio kind

Revision ID: g6h8i0j2k4l6
Revises: f4a6b8c0d2e4
Create Date: 2026-07-06

Adds the workflow_runs table that groups a multi-target train -> forecast ->
credit-analysis pipeline launched from a single New Model submission, plus a
nullable workflow_run_id FK on calibration_runs / forecast_runs /
credit_risk_runs (legacy standalone runs keep this NULL).

Also splits the datasets.kind value 'credit' into 'credit' (credit portfolio:
market_cap/vol_equity/rating) vs 'financial_portfolio' (client financial
metrics: total_assets/total_shortterm_debts/total_longterm_debts) so the
workflow launcher can resolve "latest financial portfolio dataset"
independently of "latest credit portfolio dataset". Classification is done by
sniffing schema_json for columns unique to each shape — logged for review
since it's a heuristic, not authoritative.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "g6h8i0j2k4l6"
down_revision = "f4a6b8c0d2e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column(
            "current_stage", sa.String(16), nullable=False, server_default="training"
        ),
        sa.Column(
            "triggered_by", sa.String(64), sa.ForeignKey("users.email"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("analysis_skipped_reason", sa.String(512), nullable=True),
        sa.Column(
            "calibration_dataset_id",
            sa.Integer,
            sa.ForeignKey("datasets.id"),
            nullable=False,
        ),
        sa.Column(
            "forecast_dataset_id",
            sa.Integer,
            sa.ForeignKey("datasets.id"),
            nullable=False,
        ),
        sa.Column(
            "credit_dataset_id", sa.Integer, sa.ForeignKey("datasets.id"), nullable=True
        ),
        sa.Column(
            "financial_dataset_id",
            sa.Integer,
            sa.ForeignKey("datasets.id"),
            nullable=True,
        ),
        sa.Column("targets_json", sa.Text, nullable=True),
        sa.Column("analysis_params_json", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_workflow_runs_run_id", "workflow_runs", ["run_id"], unique=True
    )
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])
    op.create_index("ix_workflow_runs_created_at", "workflow_runs", ["created_at"])

    with op.batch_alter_table("calibration_runs") as batch_op:
        batch_op.add_column(
            sa.Column("workflow_run_id", sa.Integer, nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_calibration_runs_workflow_run_id",
            "workflow_runs",
            ["workflow_run_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_calibration_runs_workflow_run_id", ["workflow_run_id"]
        )

    with op.batch_alter_table("forecast_runs") as batch_op:
        batch_op.add_column(
            sa.Column("workflow_run_id", sa.Integer, nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_forecast_runs_workflow_run_id",
            "workflow_runs",
            ["workflow_run_id"],
            ["id"],
        )
        batch_op.create_index("ix_forecast_runs_workflow_run_id", ["workflow_run_id"])

    with op.batch_alter_table("credit_risk_runs") as batch_op:
        batch_op.add_column(
            sa.Column("workflow_run_id", sa.Integer, nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_credit_risk_runs_workflow_run_id",
            "workflow_runs",
            ["workflow_run_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_credit_risk_runs_workflow_run_id", ["workflow_run_id"]
        )

    # --- dataset kind split: widen column, then backfill 'financial_portfolio' ---
    with op.batch_alter_table("datasets") as batch_op:
        batch_op.alter_column(
            "kind", existing_type=sa.String(16), type_=sa.String(32)
        )
    op.create_index("ix_datasets_kind_created_at", "datasets", ["kind", "created_at"])

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, schema_json FROM datasets WHERE kind = 'credit'")
    ).fetchall()
    reclassified = []
    for row in rows:
        try:
            cols = set(json.loads(row.schema_json or "{}").get("columns", []))
        except (TypeError, ValueError):
            continue
        looks_financial = (
            "total_shortterm_debts" in cols or "total_longterm_debts" in cols
        ) and "market_cap" not in cols
        if looks_financial:
            conn.execute(
                sa.text(
                    "UPDATE datasets SET kind = 'financial_portfolio' WHERE id = :id"
                ),
                {"id": row.id},
            )
            reclassified.append(row.id)
    if reclassified:
        print(
            f"[g6h8i0j2k4l6] Reclassified {len(reclassified)} dataset(s) from "
            f"'credit' to 'financial_portfolio' (ids: {reclassified}) based on "
            "schema sniffing — review if any look wrong."
        )


def downgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE datasets SET kind = 'credit' WHERE kind = 'financial_portfolio'"
        )
    )
    op.drop_index("ix_datasets_kind_created_at", table_name="datasets")
    with op.batch_alter_table("datasets") as batch_op:
        batch_op.alter_column(
            "kind", existing_type=sa.String(32), type_=sa.String(16)
        )

    with op.batch_alter_table("credit_risk_runs") as batch_op:
        batch_op.drop_index("ix_credit_risk_runs_workflow_run_id")
        batch_op.drop_constraint(
            "fk_credit_risk_runs_workflow_run_id", type_="foreignkey"
        )
        batch_op.drop_column("workflow_run_id")

    with op.batch_alter_table("forecast_runs") as batch_op:
        batch_op.drop_index("ix_forecast_runs_workflow_run_id")
        batch_op.drop_constraint(
            "fk_forecast_runs_workflow_run_id", type_="foreignkey"
        )
        batch_op.drop_column("workflow_run_id")

    with op.batch_alter_table("calibration_runs") as batch_op:
        batch_op.drop_index("ix_calibration_runs_workflow_run_id")
        batch_op.drop_constraint(
            "fk_calibration_runs_workflow_run_id", type_="foreignkey"
        )
        batch_op.drop_column("workflow_run_id")

    op.drop_index("ix_workflow_runs_created_at", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_run_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
