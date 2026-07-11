"""add denormalised facet columns to forecast_run_results

Revision ID: c3d5e7f9a1b3
Revises: b1c3d5e7f9a1
Create Date: 2026-07-11

Promotes sector/subsector/country/scenario out of meta_json into indexed
columns so filter-dropdown distinct queries are index scans, not full-run
pandas loads. Backfills existing rows from meta_json in id-ranged chunks
(dialect-agnostic Python, works on both SQLite tests and MSSQL prod).

DEPLOY GATES (host had no ODBC driver; not run against MSSQL here):
 - Run `flask db upgrade` then a `flask db downgrade -1 && flask db upgrade` round-trip against MSSQL before prod.
 - On a large forecast_run_results table, the four CREATE INDEX statements take a schema-modification lock; run in a maintenance window, or use ONLINE=ON (SQL Server Enterprise only) — do NOT hardcode ONLINE (fails on Standard edition).
 - Confirm production meta_json actually uses keys sector/subsector/country (only 'scenario' is confirmed in-code; the other three derive from dataset column names) before relying on the backfilled values.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "c3d5e7f9a1b3"
down_revision = "b1c3d5e7f9a1"
branch_labels = None
depends_on = None

_COLS = ("sector", "subsector", "country", "scenario")
_INDEXES = {
    "sector": "ix_frr_run_sector",
    "subsector": "ix_frr_run_subsector",
    "country": "ix_frr_run_country",
    "scenario": "ix_frr_run_scenario",
}
_LEN = {"sector": 256, "subsector": 256, "country": 128, "scenario": 128}
_CHUNK = 20_000


def upgrade():
    # Idempotent: the per-chunk commit in the backfill persists the add_column DDL
    # before Alembic stamps alembic_version, so a mid-backfill crash leaves the
    # columns in place. On re-run, skip any column/index that already exists.
    bind = op.get_bind()
    existing_cols = {
        c["name"] for c in sa.inspect(bind).get_columns("forecast_run_results")
    }
    for col in _COLS:
        if col not in existing_cols:
            op.add_column(
                "forecast_run_results",
                sa.Column(col, sa.String(_LEN[col]), nullable=True),
            )

    # Backfill from meta_json in id-ranged chunks. Each chunk's UPDATEs are sent
    # as one executemany and committed before the next chunk, so a large table
    # doesn't hold table locks or grow the transaction log for the whole run.
    t = sa.table(
        "forecast_run_results",
        sa.column("id", sa.Integer),
        sa.column("meta_json", sa.Text),
        *[sa.column(c, sa.String) for c in _COLS],
    )
    update_stmt = (
        sa.update(t)
        .where(t.c.id == sa.bindparam("row_id"))
        .values({c: sa.bindparam(c) for c in _COLS})
    )
    max_id = bind.execute(
        sa.text("SELECT COALESCE(MAX(id), 0) FROM forecast_run_results")
    ).scalar()
    lo = 0
    while lo < max_id:
        hi = lo + _CHUNK
        rows = bind.execute(
            sa.select(t.c.id, t.c.meta_json).where(
                sa.and_(t.c.id > lo, t.c.id <= hi)
            )
        ).fetchall()
        params = []
        for row in rows:
            if not row.meta_json:
                continue
            try:
                meta = json.loads(row.meta_json)
            except (TypeError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            values = {c: meta.get(c) for c in _COLS}
            if all(v is None for v in values.values()):
                continue
            params.append({"row_id": row.id, **values})
        if params:
            bind.execute(update_stmt, params)
            bind.commit()  # release locks / truncate log between chunks
        lo = hi

    existing_indexes = {
        ix["name"] for ix in sa.inspect(bind).get_indexes("forecast_run_results")
    }
    for col, name in _INDEXES.items():
        if name not in existing_indexes:
            op.create_index(name, "forecast_run_results", ["forecast_run_id", col])


def downgrade():
    bind = op.get_bind()
    existing_indexes = {
        ix["name"] for ix in sa.inspect(bind).get_indexes("forecast_run_results")
    }
    for name in _INDEXES.values():
        if name in existing_indexes:
            op.drop_index(name, table_name="forecast_run_results")

    existing_cols = {
        c["name"] for c in sa.inspect(bind).get_columns("forecast_run_results")
    }
    for col in _COLS:
        if col in existing_cols:
            op.drop_column("forecast_run_results", col)
