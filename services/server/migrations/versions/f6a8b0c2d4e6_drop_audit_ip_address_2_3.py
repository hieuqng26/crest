"""drop ip_address2 / ip_address3 from audit_logs

Revision ID: f6a8b0c2d4e6
Revises: a4b6c8d0e2f4
Create Date: 2026-07-10

The audit table carried three IP columns capturing different hops of the proxy
chain (a header field, request.access_route[-1], request.remote_addr). With
ProxyFix (x_for=4) request.remote_addr is already the real client IP, so a
single ``ip_address`` is sufficient; ``ip_address2``/``ip_address3`` are
redundant. log_audit now populates ``ip_address`` from remote_addr (or a
configured trusted header). Downgrade re-adds the columns (empty).
"""

import sqlalchemy as sa
from alembic import op

revision = "f6a8b0c2d4e6"
down_revision = "a4b6c8d0e2f4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_column("ip_address2")
        batch_op.drop_column("ip_address3")


def downgrade():
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.add_column(sa.Column("ip_address2", sa.String(45), nullable=True))
        batch_op.add_column(sa.Column("ip_address3", sa.String(45), nullable=True))
