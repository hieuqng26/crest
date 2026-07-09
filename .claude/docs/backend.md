# Backend Architecture (services/server)

Deep-dive companion to `architecture.md`. Read this before adding an endpoint,
a Celery task, or building the MCP server. The backend is layered so that
business logic is transport-agnostic and reusable by both the Flask routes and
the future MCP tools.

## Layers

```
request (HTTP route  ── or ──  MCP tool)
   │  auth (@require_perm / tool gate) + parse (Pydantic schema) + serialize (jsonify)
   ▼
project/services/<domain>.py     orchestration: ORM + core + storage + Celery dispatch
   │                             NO flask imports; raises DomainError, returns dicts/models
   ▼
project/core/<area>.py           pure computation (kmv, ecl, model_registry, table_query,
                                 dataset_io) — numpy/pandas/scipy, no ORM, no Flask
```

**The one rule that makes MCP possible:** `project/services/*` and
`project/schemas/*` must never `import flask`. Auth and (de)serialisation stay
in the caller. An MCP tool validates the same `schemas/` model, calls the same
`services/` function, and maps the same `DomainError` to a tool error — no Flask
involved. `project/core/*` is stricter still: no ORM, no Flask — just math.

## Directory map

| Path | Responsibility |
|---|---|
| `project/__init__.py` | `create_app()`, extensions (`db`, `cache`, …), `app_session()`, CORS/CSP, error-boundary + JWT registration |
| `project/config.py` | Config classes; shared `_redis_url`/`_mssql_uri`/`_minio_settings`/`_engine_options`/`_apm` builders; `validate_required_config` (prod fail-fast on missing secrets) |
| `project/constants.py` | `RunStatus`, `WorkflowStage`, `DatasetKind` (str-enums), `Progress` sentinels |
| `project/exceptions.py` | `DomainError` hierarchy → HTTP status (see below) |
| `project/api/error_handlers.py` | Global boundary: maps exceptions → JSON; **no stack traces or exception text leak to clients** |
| `project/api/helpers.py` | `get_or_404`, `pagination_envelope`, `table_query_args`, `dataframe_page_response` |
| `project/api/<domain>/routes.py` | Thin blueprints: auth → parse → service call → serialize |
| `project/schemas/<domain>.py` | Pydantic **request** schemas (response shape stays on the models' `to_dict`) |
| `project/services/<domain>.py` | Transport-agnostic orchestration |
| `project/services/run_guards.py` | Cross-domain preconditions (`ensure_not_workflow_member`) |
| `project/core/` | Pure computation incl. `dataset_io.py` (MinIO download+parse), `storage.py`, `table_query.py`, `credit_risk/`, `model_registry/` |
| `project/workers/tasks.py` | Celery tasks (see "Workers") |

## Error handling

Services raise a `DomainError` subclass; the boundary (`error_handlers.py`)
turns it into JSON. Never build error tuples in a service, and never wrap a
whole route in `try/except` — let it propagate.

| Exception | Status | Body |
|---|---|---|
| `BadRequestError` / `ValidationFailed` | 400 | `{"error": msg}` |
| pydantic `ValidationError` | 400 | `{"error": "<field>: <msg>", "detail": [...]}` |
| `ForbiddenError` | 403 | `{"error": msg}` |
| `NotFoundError` | 404 | `{"error": msg}` |
| `ConflictError` | 409 | `{"error": msg, "dependencies": {...}}` |
| `UnprocessableEntityError` | 422 | `{"error": msg}` |
| `werkzeug HTTPException` (abort/JWT) | its code | `{"message": description}` |
| any other `Exception` | 500 | `{"error": "Internal server error"}` (logged, not leaked) |

Note: `abort()`/JWT paths keep the `{"message": ...}` shape the auth/admin
frontend views read; domain/business errors use `{"error": ...}`. Both are
intentional — match the surrounding module.

`TestingConfig` sets `PROPAGATE_EXCEPTIONS = False` so integration tests exercise
this real mapping instead of Flask re-raising.

## Adding an endpoint / MCP tool (recipe)

1. Add a request schema to `project/schemas/<domain>.py` (types + `field_validator`
   for shape rules only — DB-dependent checks belong in the service).
2. Add/extend `project/services/<domain>.py`: take the schema + acting-user
   identity, do the work, raise `DomainError` on bad state, return a dict/model.
   Dispatch Celery **after** the `app_session()` commits.
3. Route: `@bp.verb` + `@require_perm("domain:action")` + `Schema.model_validate(request.get_json())`
   + call service + `jsonify`. Keep it ~3 lines. (Template: `api/model_configs/routes.py`,
   or the launch routes in calibrations/forecast_runs/workflows/credit_risk.)
4. Test the service directly (see `tests/services/test_launch_services.py`) — that
   test is also the MCP contract.

## Workers (`project/workers/tasks.py`)

- Tasks build their own app context via `_make_flask_app()` and write progress
  through `_write_progress` / `_write_forecast_progress` / `_cal_log` / `_cr_log`.
- **Failure contract:** a failed run stores the **full traceback** in
  `error_message` via `format_failure(exc)` (not `str(exc)`), plus a short
  human message in `progress_message`/logs and progress `Progress.FAILED`.
- Progress/log writers are non-fatal but **log** on failure (never bare `pass`).
- Detached-instance hazard: `app_session()` closes the shared scoped session,
  expiring held ORM instances — extract scalars immediately after a query,
  before any session-closing helper call. See
  `.claude/bugs/detached-instance-in-celery-tasks.md`.

## Status of the production-grade refactor

The service/schema/boundary layering above is in place for the **run-launching**
surface (calibration, forecast, credit-risk, workflow create/rerun) — the
MCP-critical path. Read/analysis endpoints (credit-risk heatmap/forecast,
dataset stats) and the legacy `users`/`auditlog` modules still hold logic in
their routes and are being migrated to the same pattern; `workers/tasks.py` is
slated to be split into per-domain modules with a `ProgressReporter` on an
independent session. Follow the recipe above for anything new so the surface
keeps converging rather than diverging.
