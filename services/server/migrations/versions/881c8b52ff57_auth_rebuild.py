"""auth rebuild: new roles+user_sessions, drop legacy roles+active_session, normalize role

Revision ID: 881c8b52ff57
Revises: s8t0u2v4w6x8
Create Date: 2026-06-22

Drops the legacy active_session and roles (ESG-module schema) tables.
Creates the new roles table (with 3 seeded default roles) and user_sessions table.
Normalizes users.role values to the canonical set: sysadmin / analyst / viewer.
"""

import sqlalchemy as sa
from alembic import op
from datetime import datetime, timezone


revision = "881c8b52ff57"
down_revision = "s8t0u2v4w6x8"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("active_session")
    op.drop_table("roles")  # legacy ESG-module schema

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_roles_name"), "roles", ["name"], unique=True)

    now = datetime.now(timezone.utc)
    roles_tbl = sa.table(
        "roles",
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("permissions", sa.JSON),
        sa.column("is_system", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        roles_tbl,
        [
            {
                "name": "sysadmin",
                "description": "Full administrative access. Built-in and protected.",
                "permissions": ["*"],
                "is_system": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "analyst",
                "description": "Runs the full modelling workflow.",
                "permissions": [
                    "dataset:read",
                    "dataset:write",
                    "model_config:read",
                    "model_config:write",
                    "calibration:read",
                    "calibration:write",
                    "calibration:execute",
                    "forecast:read",
                    "forecast:write",
                    "forecast:execute",
                    "evaluation:read",
                    "credit_risk:read",
                    "credit_risk:write",
                    "credit_risk:execute",
                ],
                "is_system": False,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "viewer",
                "description": "Read-only access to the modelling workflow.",
                "permissions": [
                    "dataset:read",
                    "model_config:read",
                    "calibration:read",
                    "forecast:read",
                    "evaluation:read",
                    "credit_risk:read",
                ],
                "is_system": False,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    op.create_table(
        "user_sessions",
        sa.Column("sid", sa.String(length=36), nullable=False),
        sa.Column("user_email", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["user_email"], ["users.email"]),
        sa.PrimaryKeyConstraint("sid"),
    )
    op.create_index(op.f("ix_user_sessions_user_email"), "user_sessions", ["user_email"])

    op.execute("UPDATE users SET role='sysadmin' WHERE role IN ('admin','administrator')")
    op.execute("UPDATE users SET role='viewer' WHERE role NOT IN ('viewer','analyst','sysadmin')")


def downgrade():
    op.drop_index(op.f("ix_user_sessions_user_email"), table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index(op.f("ix_roles_name"), table_name="roles")
    op.drop_table("roles")

    # Recreate legacy active_session table
    op.create_table(
        "active_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_email", sa.String(length=64), nullable=False),
        sa.Column("session_token", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Recreate legacy roles table (ESG-module schema)
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("module", sa.String(length=64), nullable=True),
        sa.Column("permission_type", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
