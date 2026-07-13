# Backend Architecture (services/server)

Deep-dive companion to `architecture.md`. Read this before adding an endpoint,
a Celery task, or an MCP tool. The backend is layered so that business logic
is transport-agnostic and reused by both the Flask routes and the MCP server
(`project/mcp_server/` — see "MCP server" below).

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

## Request guarding

There is **no hand-rolled input WAF** (the old `validate_request` regex filter
was removed — a bypassable blocklist that guarded no real sink). The layered,
principled controls are:

- **Validation** = strict Pydantic schemas (`extra="forbid"` + `max_length` +
  field validators). Unknown keys are rejected; SQLi/XSS are *not* addressed here.
- **SQL injection** is prevented by the SQLAlchemy ORM (parameterized) everywhere.
  The one raw-SQL surface — `datasets /query` (user SQL) — is bounded by a query
  timeout + row cap, and its real write-prevention is a **read-only `RISK_DB`
  login** (`db_datareader`), documented in `env/.env.example.*`. The `SELECT/WITH`
  check is fast-fail UX, not the boundary.
- **Body size**: `MAX_CONTENT_LENGTH` (config, env `MAX_CONTENT_LENGTH_MB`) → 413.
- **Rate limiting**: `flask-limiter` (Redis-backed, per client IP via ProxyFix) on
  the auth endpoints (`RATELIMIT_AUTH`); complements the login lockout. Disabled
  effectively in tests via a huge limit. A 429 flows through the boundary as
  `{"message": ...}`.
- Output encoding + CSP (frontend) handle XSS; do not filter it on input.

## Adding an endpoint / MCP tool (recipe)

1. Add a request schema to `project/schemas/<domain>.py` (types + `field_validator`
   for shape rules only — DB-dependent checks belong in the service).
2. Add/extend `project/services/<domain>.py`: take the schema + acting-user
   identity, do the work, raise `DomainError` on bad state, return a dict/model.
   Dispatch Celery **after** the `app_session()` commits.
3. Route: `@bp.verb` + `@require_perm("domain:action")` + `Schema.model_validate(request.get_json())`
   + call service + `jsonify`. Keep it ~3 lines. (Template: `api/model_configs/routes.py`,
   or the launch routes in calibrations/forecast_runs/workflows/credit_risk.)
   For an MCP tool the caller is instead a `crest_*` function in
   `project/mcp_server/tools/` — `@mcp.tool(name=..., annotations=...)` +
   `@tool_boundary` + call service. Same thinness rule.
4. Test the service directly (see `tests/services/test_launch_services.py` and
   `test_read_services.py`) — those tests are also the MCP contract; tool-level
   tests live in `tests/mcp_server/`.

## MCP server (`project/mcp_server/`)

An MCP server exposing 27 `crest_*` tools (launch + monitor + reads) — a sibling
transport to `project/api/` that calls the same `services/` functions and
validates the same `schemas/` models. `MCP_TRANSPORT` selects **stdio** (default,
local) or **streamable-http** (remote: the `mcp` compose service on `:8090/mcp`,
bearer-token auth via `MCP_AUTH_TOKEN`, fail-closed without it — see
`docs/api/mcp-server.md`).

- **Run**: `python -m project.mcp_server` from `services/server/`. It calls
  `create_app()`, so it needs the app's **native deps** (`pyodbc`/unixodbc) and
  env (`CONFIG_NAME`, `JWT_SECRET_KEY` — hard-required even though MCP mints no
  JWTs — plus DB/Redis/MinIO). Because the debug stack runs the backend in
  **Docker** (`build_debug.sh up`) and the host usually lacks unixodbc, the
  recommended registration runs the server **inside the backend container**,
  where those deps + `env/.env.dev` already exist:
  `docker compose -f docker-compose.debug.yml exec -T backend python3 -m project.mcp_server`.
  Copy `.mcp.json.example` (repo root) → `.mcp.json` for the Claude Code
  wiring (both the container form and a host-run alternative are documented
  there). The debug image installs the MCP SDK (`services/server/Dockerfile`);
  `requirements-mcp.txt` is the host-run equivalent. Celery + Redis must run for
  launched jobs to execute.
- **Host gotchas** (only if running the server on the host, not the container):
  `docker-compose.debug.yml` publishes MinIO on **9100** (not 9000) and does
  **not** publish redis — so a host-run server can read the DB but can't reach
  MinIO/redis at the obvious ports. Running inside the container avoids all of
  this.
- **Layout**: `server.py` (FastMCP instance + registration), `runtime.py`
  (`get_app()` singleton, `MCP_IDENTITY`, `tool_boundary`), `tools/{launch,
  runs,results,refs,analysis}.py`.
- **Identity**: `MCP_IDENTITY` env (default `mcp-agent`) is passed as the
  services' `identity` arg → `triggered_by`. No RBAC in v1.
- **Boundary**: `tool_boundary` mirrors `error_handlers.py` — `DomainError` →
  `ToolError("[<code>] <message>")`, unexpected exceptions → logged +
  generic `"Internal server error"` (never leaked). It also pushes a Flask
  **app context per call** and removes the scoped session after — FastMCP runs
  sync tools on worker threads, so never hoist one global app context.
- **stdout is the protocol**: everything must log to stderr.
  `runtime.get_app()` force-disables `SQLALCHEMY_ECHO` before `create_app()`
  (engines are created in `init_app` and echo writes to stdout).
- **Context budget**: every list/log/result tool is paginated with hard caps
  (100 items / 200 rows / 500 log lines); calibration diagnostics are always
  slimmed (no `val_obs`/`train_obs`). Don't add an "all rows" path.
- **Not exposed in v1**: dataset upload/query/stats, model-config CRUD,
  cancel/delete, segment recalibrate, set-active, transitions matrix,
  client list.

## Workers (`project/workers/`)

`tasks.py` is a thin re-export **shim**; the task bodies live in per-domain
modules so `include=["project.workers.tasks"]` still registers all 8 tasks and
`from project.workers.tasks import X` keeps working:

| Module | Contents |
|---|---|
| `common.py` | `format_failure`, `_make_flask_app`, the four progress/log writers, dataset loaders, shared slot constants — no task defs, no cross-task dispatch |
| `calibration.py` | `run_calibration`, `run_segment_calibration` + CV/segmentation/fit helpers |
| `forecast.py` | `run_forecast`, `recompute_forecast_run_segment` + scoring helpers |
| `credit.py` | `run_credit_analysis`, `backfill_analysis_series` + portfolio compute |
| `segments.py` | `recompute_segment_downstream` |
| `workflow.py` | `advance_workflow(_impl)`, `delete_workflow` |
| `context.py` | `worker_session()` (independent Session — the detached-instance fix) |

- Tasks are **mutually recursive** (`advance_workflow` ⇄ `run_forecast`/
  `run_credit_analysis`; `run_segment_calibration` → `recompute_segment_downstream`).
  Those cross-task `.delay()` refs use **deferred (function-local) imports** to
  break the otherwise-cyclic module graph; helper cross-imports stay top-level.
- **Failure contract:** a failed run stores the **full traceback** in
  `error_message` via `format_failure(exc)` (not `str(exc)`), plus a short
  human message in `progress_message`/logs and progress `Progress.FAILED`.
- Progress/log writers are non-fatal but **log** on failure (never bare `pass`),
  and write via `worker_session()` (an independent Session) so they can't detach
  the ORM objects a task holds. `app_session()` (which closes the shared scoped
  session) is still fine for a task's own start/end writes. See
  `.claude/bugs/detached-instance-in-celery-tasks.md`.
- Patching note: patch a *task object's* attribute (`...run_forecast.delay`) from
  the shim; patch a *plain function the task calls* (`_make_flask_app`, `storage`)
  on the module that runs it (e.g. `project.workers.calibration._make_flask_app`).

## Status of the production-grade refactor

In place: the service/schema/boundary layering for the **run-launching** surface
(calibration/forecast/credit-risk/workflow create + rerun), the **read surface**
(run list/get, logs — `services/run_logs.py`, results, diagnostics, dataset/
model-config/pd-rating listings) and the **credit-risk analysis reads**
(`services/credit_analysis.py` builders + `services/credit_risk_analysis.py`
loaders, which the Celery materializer also reuses — no more worker/core
imports from route modules); the **MCP server** (`project/mcp_server/`, above);
`extensions.py`; `SerializerMixin` for plain-column `to_dict`; and the
`workers/` decomposition + `worker_session` fix above.

The `validate_request` regex WAF has been removed and replaced by the strict
Pydantic + ORM + body-cap + rate-limit model above (see "Request guarding");
`users`/`auditlog` are on the unified `@bp.verb` + schema style.

Still route-resident (lower priority — not MCP-exposed): the datasets
upload/query/stats handlers (transport-bound file/SQL).
Follow the recipe above for anything new so the surface keeps converging.
