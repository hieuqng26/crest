"""add export_jobs table

Revision ID: d5e7f9a1b3c5
Revises: c3d5e7f9a1b3
Create Date: 2026-07-13

Backs the workflow Download tab: each row is one asynchronous build of a
downloadable output file (csv/xlsx) produced by the ``export_dataset`` Celery
task on the dedicated ``exports`` queue and stored in MinIO.
"""

import sqlalchemy as sa
from alembic import op

revision = "d5e7f9a1b3c5"
down_revision = "c3d5e7f9a1b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column(
            "workflow_run_id",
            sa.Integer,
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column("output_key", sa.String(64), nullable=False),
        sa.Column("fmt", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("progress_message", sa.String(512), nullable=True),
        sa.Column("object_path", sa.String(512), nullable=True),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("mimetype", sa.String(128), nullable=True),
        sa.Column("row_count", sa.Integer, nullable=True),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("triggered_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("expires_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "ix_export_jobs_job_id", "export_jobs", ["job_id"], unique=True
    )
    op.create_index(
        "ix_export_jobs_workflow_run_id", "export_jobs", ["workflow_run_id"]
    )
    op.create_index("ix_export_jobs_created_at", "export_jobs", ["created_at"])


def downgrade():
    op.drop_index("ix_export_jobs_created_at", table_name="export_jobs")
    op.drop_index("ix_export_jobs_workflow_run_id", table_name="export_jobs")
    op.drop_index("ix_export_jobs_job_id", table_name="export_jobs")
    op.drop_table("export_jobs")
