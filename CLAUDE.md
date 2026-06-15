# Banking ML Calibration Platform — Claude Operational Guide

## Project Identity

This is a **banking-grade ML calibration platform** for quantitative analysts and risk modellers.
Primary workflow: **Ingest → Configure → Calibrate → Evaluate → Forecast → Credit Risk**.
All design decisions prioritise security, auditability, statistical rigour, and reproducibility.

See `PLAN.md` for the full architecture. This file is operational guidance for Claude sessions.

## Model Policy

- **Default:** `claude-sonnet-4-6` — routine tasks (edits, scaffolding, API wiring, bug fixes).
- **Switch to `claude-opus-4-7`** for: new abstraction design (model registry, diagnostics engine), multi-file architectural refactors, statistical/credit-risk logic, or any task requiring deep cross-file reasoning.
- If mid-task complexity warrants Opus, **stop and ask the user to switch** rather than producing a shallow result on Sonnet.

---

## Repository Layout

```
services/
  client/          Vue 3 frontend (PrimeVue 3 + Vuex + Tailwind + Vite)
  server/          Flask backend (SQLAlchemy + JWT + Celery + SocketIO)
env/
  .env.dev         Dev secrets (never commit)
  .env.prod        Prod secrets (never commit)
docker-compose.debug.yml    Local dev stack
docker-compose.prod.yml     Production stack
PLAN.md            Full architecture reference
IDEA.md            Original brief
```

### Frontend structure

```
services/client/src/
  api/             Axios wrappers (one file per domain)
  layout/          AppLayout, AppMenu, AppTopbar, AppSidebar, AppFooter
  store/           Vuex modules (actions/ per domain)
  router/index.js  All routes + auth guard
  views/           One folder per feature module
  components/      Reusable charts and tables
```

### Backend structure

```
services/server/project/
  api/             Flask blueprints (one folder per domain)
  core/            Business logic (model_registry, calibration, diagnostics, credit_risk)
  db_models/       SQLAlchemy ORM models
  workers/tasks.py Celery async tasks
  config.py        Config classes (Dev/Prod/Test)
  logger.py        Structured logger
  __init__.py      App factory (create_app)
```

---

## Stack Cheat Sheet

| Layer | Technology |
|---|---|
| Frontend | Vue 3 (Composition API, `<script setup>`), PrimeVue 3, Vuex 4, Vue Router 4, Tailwind CSS 3, Vite |
| Charts | apexcharts + vue3-apexcharts, chart.js, plotly.js-dist |
| HTTP | axios (httpClient.js handles JWT headers + refresh) |
| Realtime | socket.io-client (Vue) ↔ Flask-SocketIO (server, threading mode) |
| Backend | Python / Flask 3, SQLAlchemy 3, Flask-JWT-Extended, Flask-Migrate (Alembic) |
| Async | Celery 5 + Redis broker/result backend |
| DB | MSSQL (app DB) + MSSQL risk DB (read-only live queries) |
| Artifact store | MinIO (S3-compatible) for model pickles, uploaded files, diagnostics |
| Experiment tracking | MLflow server (headless — never expose its UI to users) |
| Config validation | Pydantic v2 |
| Auth | JWT (access + refresh tokens in headers/cookies), RBAC via roles table |

---

## Conventions

### Python / Backend

- All new API modules follow the pattern: `api/<domain>/__init__.py` + `routes.py` + `models.py` (if new tables).
- Register blueprints in `project/__init__.py` `create_app()`.
- Business logic lives in `project/core/`, not in route handlers.
- Celery tasks in `project/workers/tasks.py`. Each task emits SocketIO progress via `send_notification()`.
- All new DB tables get an Alembic migration. Run `flask db migrate -m "description"` then `flask db upgrade`.
- Use the `app_session()` context manager for transactional DB writes.
- Pydantic models validate all incoming JSON configs before any DB write or task dispatch.
- Log with `get_logger(__name__)` — never `print()`.
- Return errors as `{"error": "message"}, status_code`. No stack traces to client.

#### Python formatting (enforced by `ruff`)

- **All imports at the top of the file** — never inside functions or conditionals, except when a deferred import is strictly required to avoid a circular import or a missing app context (document why with a comment).
- Import order: stdlib → third-party → local (`project.*`), each group separated by one blank line.
- Line length: 88 characters (ruff default).
- Strings: double quotes throughout.
- After any Python edit run: `ruff check . --exclude migrations --fix && ruff format . --exclude migrations` from `services/server/`. All checks must pass before the work is considered done.

### Vue / Frontend

- Composition API with `<script setup>` everywhere. No Options API.
- Vuex for global auth/job/notification state. Use composables or component-local `ref/reactive` for page-level state.
- All API calls go through `src/api/` wrappers — never raw `axios` in a component.
- New page = new view file in `src/views/<module>/` + route entry in `router/index.js` + menu entry in `AppMenu.vue`.
- PrimeVue components preferred over custom HTML for forms, tables, dialogs. Tailwind for layout/spacing only.
- Charts: apexcharts for time-series and bar/line, chart.js for simple pie/donut, plotly.js-dist for statistical residual plots.
- Dark theme is default (`ey-dark`). Never use EY Yellow `#FFE600` as text on light surfaces.
- Mock data pattern: put mock JSON in `src/views/<module>/mock/` and swap with real API calls in Phase 3.

#### Vue / JS formatting (enforced by Vite's built-in ESLint + Prettier conventions)

- **All imports at the top of `<script setup>`** — never inside functions.
- Import order within `<script setup>`: Vue core (`vue`, `vue-router`, `pinia/vuex`) → third-party (PrimeVue, etc.) → local `@/api/`, `@/utils/`, relative components.
- Single blank line between import groups.
- Shared utilities (date formatting, number formatting, etc.) go in `src/utils/` and are imported — never duplicated inline across components.
- Datetime formatting must use `fmtDate` / `fmtDateShort` from `@/utils/datetime.js`. Never call `toLocaleDateString` / `toLocaleTimeString` directly in a component.

### UI design principles

Every page Claude touches must follow these rules — no exceptions. They are non-negotiable, even when adding "just one quick field":

- **Clean and modern, not corporate-default.** Prefer flat panels (`surface-card` + 1px `surface-border` + 12px radius) over heavy `shadow-1` cards. Strip stripes, default backgrounds, and chrome that don't carry information.
- **Information hierarchy is the design.** Page title is `text-3xl tracking-tight`. Section titles are tiny uppercase (`0.7rem`, `letter-spacing: 0.06em`, muted color). Numbers and identifiers are larger and lighter; everything supporting them is smaller and muted. Never give two elements equal weight unless they are equal.
- **Don't dump everything on screen.** If a page has >5 controls or >4 sections, ask what's secondary and hide it: overflow `⋮` menus for row actions, `OverlayPanel` for filter detail, tabs for parallel views, drawers/dialogs for create flows. The default view should answer the user's most likely question; everything else is one click away.
- **Smart compression over verbose dumps.** Stage tags → colored dots + label. Six KPI cards → one flat strip with dividers. Big legend boxes → small pills above the chart. Status icon + Tag + label trio → one colored dot + one word.
- **Smooth, predictable workflow.** Primary action lives in the page header, top-right. Filters live above the table, never inside it. Tabs and segmented controls (status / portfolio / scaler) all use the same pill component. URLs reflect state (`?tab=`, `?algorithm=`) so users can share and back-navigate.
- **Empty / loading / error states are first-class.** Dashed-border placeholders with a muted icon and one short sentence — not blank divs.
- **Consistency across pages.** Reuse the same patterns established in `views/calibrate/CalibrateJobs.vue`, `CalibrateRun.vue`, `views/credit_risk/CreditRiskECL.vue`: segmented pill (`.seg-pill` / `.status-pill`), flat panel (`.panel`), status dot with ping, custom thin progress track, flat-table `:deep()` rules. Don't invent a new card style if one already exists.
- **PrimeVue components, custom styling.** Use PrimeVue for behavior (DataTable, Dropdown, Menu, OverlayPanel, Chart). Override default look with scoped `:deep()` to match the language above — defaults are too busy.
- **Test the feel.** A finished page should let the user do the most likely action without reading documentation. If you have to add a tooltip to explain what something does, the design isn't done yet.

When redesigning an existing page, always look at `CalibrateJobs.vue` and `CalibrateRun.vue` first — they are the reference implementation for the visual language.

### General

- No comments explaining WHAT code does — only WHY (non-obvious constraints, workarounds).
- No unused imports, dead code, or backwards-compat shims.
- When adding a new feature, follow the exact same shape as an existing analogous feature.

---

## Auth & Security Rules

- JWT access token (10 min expiry) + refresh token (720 min). Both validated in `isValidJwt()` on the frontend.
- All `/api/*` routes except `/api/auth/login` and `/api/ping` require `@jwt_required()`.
- RBAC roles are checked per-route via the `roles` table. Roles: `sysadmin`, `analyst`, `viewer`.
  - `analyst`: can upload data, create configs, trigger calibration.
  - `viewer`: read-only access to all runs and diagnostics.
- Never expose MLflow UI or Celery Flower to users — internal ops tooling only.
- No secrets in code. All in `env/.env.dev` / `env/.env.prod` (gitignored).
- CSRF disabled for JWT-only API. Do not re-enable without understanding the existing CORS/CSP setup.

---

## Running Locally

```bash
# 1. Copy env file
cp env/.env.dev env/.env.dev   # already exists, adjust secrets if needed

# 2. Start infrastructure
docker compose -f docker-compose.debug.yml up -d redis mssql minio mlflow

# 3. Apply DB migrations
cd services/server
flask db upgrade

# 4. Start backend (hot reload)
flask run --port 5001 --debug
# or via Docker: docker compose -f docker-compose.debug.yml up backend

# 5. Start frontend (hot reload)
cd services/client
npm run dev   # → http://localhost:5173

# 6. Start Celery worker
cd services/server
celery -A project.workers.tasks worker --loglevel=info
```

---

## Model Registry Rules

- Every algorithm is a class inheriting `BaseMLModel` in `project/core/model_registry/`.
- The class must implement: `fit()`, `predict()`, `diagnostics()`.
- Register in `project/core/model_registry/__init__.py` `REGISTRY` dict.
- Param schema is a Pydantic `BaseModel` — required, no raw `**kwargs`.
- Never change a plugin class in a way that breaks existing serialised pickles. Create a new plugin version instead.

---

## Calibration Job Rules

- Every run gets a UUID `run_id`. It is immutable once created.
- Progress is emitted via SocketIO events: `{"run_id": "...", "progress": 0-100, "message": "..."}`.
- On success: artifact stored in MinIO, `calibration_runs.status = "success"`, metrics in `val_metrics_json`.
- On failure: `calibration_runs.status = "failed"`, full traceback in `error_message`. Job never silently swallowed.
- Recalibration always creates a new `run_id` — the old run is never mutated.

---

## Diagnostic Metric Matrix

| Family | Required Metrics |
|---|---|
| Classification | AUC-ROC, KS statistic, Gini, accuracy, precision, recall, F1, confusion matrix, calibration curve, Hosmer-Lemeshow test, feature importance |
| Time-series | RMSE, MAE, MAPE, R², ACF/PACF of residuals, Ljung-Box Q-test, Breusch-Pagan heteroscedasticity |
| Statistical | Coefficients + SE + p-values, VIF, log-likelihood, AIC, BIC, deviance residuals, goodness-of-fit χ² |

---

## Known Issues / Constraints

- `gevent` is used in production SocketIO; `threading` mode used in dev to avoid ORE C++ conflicts. Do not change without testing both.
- MSSQL driver: `pyodbc` with `ODBC Driver 17 for SQL Server`. The container must have the driver installed (handled in Dockerfile).
- `WTF_CSRF_ENABLED=False` in dev — intentional for API-only use. Do not change.
- PrimeVue 3 is pinned (not v4) — API is different between major versions. Do not upgrade without full audit.
