"""add kind column to datasets

Revision ID: j5k7l9m1n3o5
Revises: i4j6k8l0m2n4
Create Date: 2026-06-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "j5k7l9m1n3o5"
down_revision = "i4j6k8l0m2n4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "datasets",
        sa.Column(
            "kind",
            sa.String(16),
            nullable=False,
            server_default="calibration",
        ),
    )


def downgrade():
    op.drop_column("datasets", "kind")
