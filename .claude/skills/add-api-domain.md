# Skill: Add a backend API domain

When adding a new feature area that needs its own endpoints.

## Steps
1. Create `services/server/project/api/<domain>/` with:
   - `__init__.py` — `from flask import Blueprint; <domain> = Blueprint("<domain>", __name__)` then `from . import routes`.
   - `routes.py` — handlers on that blueprint.
2. If it needs new tables, add models in `db_models/` and a migration
   (`.claude/skills/add-db-migration.md`).
3. Register the blueprint in `project/__init__.py` `create_app()` with its url_prefix
   (e.g. `/api/<domain>`), next to the existing `app.register_blueprint(...)` calls.
4. Put business logic in `project/core/`, NOT in the handler.
5. Validate every incoming JSON body with a Pydantic model before any DB write or
   task dispatch.
6. Guard routes with `@jwt_required()` (all `/api/*` except login/ping). Add RBAC
   role checks where needed.
7. Long work → dispatch a Celery task in `workers/tasks.py`; return `{run_id}`
   immediately. Persist progress/logs to a `*_run_logs` table (no SocketIO).
8. Errors: `return jsonify({"error": "message"}), <status>`. Never leak a traceback.
9. Log via `get_logger(__name__)`.
10. Run `ruff check . --exclude migrations --fix && ruff format . --exclude migrations`
    from `services/server/`.

## Conventions
- Imports at top of file, ordered stdlib → third-party → `project.*`.
- Use the `app_session()` context manager for transactional writes.
- Mirror the shape of an existing domain (`calibrations`, `forecast_runs`) — don't
  invent a new structure.
