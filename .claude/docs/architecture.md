# Architecture

End-to-end structure of CREST. Read this before any cross-cutting change.

## Repository layout

```
services/
  client/   Vue 3 frontend (PrimeVue 3 + Vuex + Tailwind + Vite)
  server/   Flask backend (SQLAlchemy + JWT + Celery)
env/        .env.dev / .env.prod  (gitignored — never commit secrets)
docker-compose.debug.yml   Local dev stack (redis, mssql, minio, mlflow, backend)
docker-compose.prod.yml    Production stack
```

## Backend (`services/server/project/`)

```
api/             Flask blueprints, one folder per domain:
                 auth, users, roles, datasets, model_configs, calibrations,
                 evaluations, forecasts, forecast_runs, credit_risk, auditlog
core/            Business logic (NOT in route handlers):
                 model_registry/   ML plugin system (see below)
                 calibration/      training orchestration
                 diagnostics/      metric computation
                 credit_risk/      kmv.py, ecl.py, mock_credit.py
                 storage.py        MinIO artifact I/O
db_models/       SQLAlchemy ORM (see .claude/docs/database_models.md)
workers/tasks.py Celery async tasks (calibration, forecast, credit-risk runs)
config.py        Dev / Prod / Test config classes
logger.py        get_logger(__name__) — structured logging, never print()
__init__.py      App factory create_app(); register every new blueprint here
```

**Request lifecycle (write/compute path):** route handler → Pydantic validation of
JSON body → `app_session()` transactional DB write → dispatch Celery task → return
`{run_id}`. The Celery task does the heavy work, persists progress/logs to DB rows,
and writes artifacts to MinIO. Errors return `{"error": "message"}, status_code`
— never a stack trace.

**Auth & RBAC:** every `/api/*` route except `/api/auth/login` and `/api/ping` requires
`@jwt_required()`. Fine-grained access is enforced by `@require_perm("domain:action")`
(`api/auth/decorators.py`). The permission catalog (`api/auth/permissions.py`) defines
9 domains × `{read, write, execute}` actions (delete folded into write). Roles are stored
in the `roles` table with a `permissions` JSON column; looked up per-request via a
5-min cached registry (`api/roles/registry.py`) so role edits apply without re-login.
Three built-in roles are seeded: `sysadmin` (wildcard `["*"]`, `is_system`), `analyst`,
`viewer`; `sysadmin` cannot be deleted or renamed. `current_role()` and
`current_permissions()` helpers are also in `api/auth/decorators.py`.
Sessions are stored in the `user_sessions` table (see `database_models.md`) and are
single-session-per-user; login revokes prior sessions. See `state_management.md` for the
cookie/CSRF/refresh flow and the frontend `/auth/me` bootstrap.

**Auth module layout (`api/auth/`):**
- `permissions.py` — `PERMISSION_CATALOG`, `has_permission`, `normalize_permissions`,
  `catalog_payload`, `SUPERUSER="*"`
- `models.py` — `UserSession` ORM model (`user_sessions` table)
- `sessions.py` — `create_session`, `revoke_session`, `revoke_all_for_user`,
  `is_revoked`, `purge_expired`
- `jwt_callbacks.py` — `register_jwt_callbacks` (blocklist check + error handlers)
- `security.py` — login lockout (5 failures → 15 min lock) + `validate_password_strength`
- `decorators.py` — `require_perm(permission)`, `current_role()`, `current_permissions()`
- `routes.py` — `login` (httpOnly cookies, single session), `refresh`, `logout`, `me`,
  `change-password`

**Roles module layout (`api/roles/`):**
- `models.py` — `RoleModel` (`roles` table: `name`, `description`, `permissions` JSON,
  `is_system`, `created_by`, timestamps)
- `defaults.py` — `SYSADMIN_ROLE`, `ensure_default_roles()` (seeds built-ins at startup)
- `registry.py` — `permission_map()`, `permissions_for(role_name)`, `invalidate()` —
  5-min cache; use Redis backend in production for shared invalidation across gunicorn workers
- `routes.py` — `roles_bp` at `/api/roles`: GET catalog, GET /, POST /, PUT /\<name>,
  DELETE /\<name> (protected by `role:read`/`role:write` permissions)

## Frontend (`services/client/src/`)

```
api/        Axios wrappers, one per domain. httpClient.js = JWT + refresh interceptor.
            NEVER call raw axios in a component.
store/      Vuex (auth, roles, user, log). Persisted via vuex-persistedstate.
router/index.js   All routes + auth guard.
layout/     AppLayout, AppTopbar, AppMenu (sidebar), AppFooter.
views/      One folder per feature module (calibrate, forecast, credit_risk,
            configure, ingest, auth).
components/ Reusable Charts/ and Table/ widgets.
utils/      Shared helpers — datetime.js (fmtDate/fmtDateShort), number fmt, isValidJwt.
assets/layout/_brand.scss   Theme token + component override layer (see design.md).
```

**Adding a page:** new view in `views/<module>/` + route in `router/index.js` +
menu entry in `AppMenu.vue` + an `api/` wrapper. See `.claude/skills/add-frontend-page.md`.

## Core quantitative logic (`core/credit_risk/`)

Two-stage pipeline, both operate per-client over a multi-scenario yearly forecast
(scenarios e.g. Baseline / Adverse / Severely Adverse):

1. **KMV (`kmv.py`)** — Merton structural model. Inputs: market cap `E0`, equity
   vol `volE`, risk-free `r`, credit `rating`, plus a forecast of asset values per
   year/scenario. Solves asset value & volatility (`scipy.optimize.root_scalar`,
   `scipy.stats.norm`), derives distance-to-default → **PD** per year/scenario, maps
   rating → **LGD** via the `pd_rating` table.

2. **ECL (`ecl.py`)** — IFRS 9 Expected Credit Loss. Inputs: PD/LGD per year/scenario,
   exposure `EAD`, discount rate `r`, lifetime horizon. Computes the **marginal
   (conditional) PD** `(PD_t − PD_{t-1}) / (1 − PD_{t-1})`, then
   `ECL = EAD · LGD · Disc · ΔConditionalPD`, producing 12-month and lifetime ECL
   per scenario. This conditional-PD weighting across years is the project's core
   calculation.

## Model registry (`core/model_registry/`)

- Every algorithm is a class subclassing `BaseMLModel` (`base.py`) implementing
  `fit()`, `predict()`, `diagnostics()`.
- Registered in the `REGISTRY` dict in `__init__.py`. Current: LogisticRegression,
  GLM_Binomial, SVM (classification); GradientBoosting, RandomForest (ensemble);
  LinearRegression, Ridge, Lasso, ElasticNet (regression); ARIMA (time series).
- Param schema is a Pydantic `BaseModel` — required, no raw `**kwargs`.
- Never mutate a plugin in a way that breaks existing serialised pickles — add a new
  version. See `.claude/skills/add-model-plugin.md`.

## Calibration / run lifecycle

- Every run has an immutable UUID `run_id`. Recalibration creates a NEW run_id;
  old runs are never mutated.
- Success: artifact in MinIO, `status="success"`, metrics in `val_metrics_json`.
- Failure: `status="failed"`, full traceback in `error_message`. Never silently swallowed.
- Progress/logs are persisted to DB rows (`*_run_logs` tables); the frontend polls.
  (SocketIO was fully removed — do not reintroduce it.)

## Infra constraints

- MSSQL via `pyodbc` + `ODBC Driver 17 for SQL Server` (installed in Dockerfile).
- MinIO is S3-compatible; all model pickles, uploads, diagnostics live there.
- MLflow runs headless — never expose its UI or Celery Flower to users.
- PrimeVue 3 is pinned (v4 API differs). Do not upgrade without a full audit.
