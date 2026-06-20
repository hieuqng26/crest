# Skill: Add a database migration

Every schema change (new table, column, index, FK) needs an Alembic migration.

## Steps
From `services/server/` (infra running — see `.claude/docs/` dev commands):
1. Edit/add the model in `project/db_models/`.
2. Keep `to_dict()` (or the serializer) in sync with new columns.
3. Generate: `flask db migrate -m "short description"`.
4. **Review the generated file** in `migrations/versions/` — autogenerate misses
   some things on MSSQL (server defaults, FK `ondelete`, type changes). Edit by hand
   where needed.
5. Apply: `flask db upgrade`.
6. Confirm `down_revision` chains correctly to the previous head.

## Notes
- DB is **MSSQL** via `pyodbc` + `ODBC Driver 17`. Some Postgres-isms don't apply.
- FK cascades matter — see the dependency chain in
  `.claude/docs/database_models.md`. If a child should auto-delete with its parent,
  set `ondelete="CASCADE"` explicitly (autogenerate won't infer intent).
- `ruff` excludes `migrations/` — don't run the formatter over them.
- Never edit an already-applied migration; add a new one.
