# CREST — Banking ML Calibration Platform

High-level index for agents. **Deep detail is intentionally elsewhere** — read the
relevant file in `.claude/docs/` (domain knowledge), `.claude/skills/` (reusable
procedures), or `.claude/bugs/` (fixed-bug patterns) before working in that area.
Update those folders as you learn; keep this file short.

## 1. Project Overview

CREST is a banking-grade ML calibration platform for quantitative analysts and risk
modellers. It runs the workflow **Ingest → Configure → Calibrate → Evaluate →
Forecast → Credit Risk**: users upload datasets, calibrate ML/statistical models,
generate forward-looking forecasts, and compute IFRS 9 credit-risk metrics (KMV PD,
ECL) per client. Priorities: security, auditability, statistical rigour, reproducibility.

## 2. Tech Stack

**Frontend** (`services/client`): Vue 3.4 (Composition API, `<script setup>`),
PrimeVue **3.51 — pinned, NOT v4**, Vuex 4 (+ vuex-persistedstate), Vue Router 4,
Tailwind 3.4, Vite 5; axios 1; charts apexcharts 5 / chart.js 4 / plotly.js 2.

**Backend** (`services/server`): Python / Flask, Flask-SQLAlchemy 3, Flask-JWT-Extended,
Flask-Migrate 4 (Alembic), Celery 5.4 + Redis, Pydantic 2; quant: numpy 2, pandas 2.2,
scipy 1.14, scikit-learn, statsmodels.

**Infra**: MSSQL (app DB, via pyodbc + ODBC Driver 17), MinIO (artifacts/files),
MLflow (headless tracking — never expose the UI). Local stack: `docker-compose.debug.yml`.

→ Full structure & request lifecycle: `.claude/docs/architecture.md`.

## 3. Dev Commands

```bash
# Infrastructure (redis, mssql, minio, mlflow)
docker compose -f docker-compose.debug.yml up -d redis mssql minio mlflow

# Backend  (from services/server/)
pip install -r requirements.txt
flask db upgrade                                   # apply migrations
flask run --port 5001 --debug                      # dev server
celery -A project.workers.tasks worker --loglevel=info   # async worker

# Frontend (from services/client/)
npm install
npm run dev      # dev server → http://localhost:5173
npm run build    # production build
```

After any Python edit, from `services/server/`:
`ruff check . --exclude migrations --fix && ruff format . --exclude migrations`.

## 4. Core Logic Summary

The quantitative core is a two-stage per-client credit-risk pipeline over a
multi-scenario yearly forecast (Baseline / Adverse / Severely Adverse), in
`services/server/project/core/credit_risk/`:

1. **KMV** (`kmv.py`) — Merton structural model. From market cap, equity volatility,
   risk-free rate, rating + asset-value forecast it solves distance-to-default →
   **PD** per year/scenario, and maps rating → **LGD** via the `pd_ratings` table.
2. **ECL** (`ecl.py`) — IFRS 9. From PD/LGD, exposure (EAD) and discount rate it
   computes the **marginal (conditional) PD** `(PD_t − PD_{t-1})/(1 − PD_{t-1})` and
   `ECL = EAD · LGD · Disc · ΔConditionalPD` → 12-month and lifetime ECL per scenario.
   This conditional-PD-across-years weighting is the central calculation.

Model training is plugin-based (`core/model_registry/`). Details + diagnostic-metric
matrix: `.claude/docs/architecture.md`.

## 5. Key Constraints

- **Production-grade by default.** This is a banking application — every contribution(code structure, design patterns, UI/UX, database schema, queries, API design) must be built for scalability and performance, not as a prototype. Avoid N+1 queries, index foreign keys and filtered/sorted columns, paginate large result sets, keep heavy work in Celery, and reuse existing abstractions instead of one-off hacks. No throwaway shortcuts.
- **PrimeVue stays on v3** (v4 API differs). Don't upgrade without a full audit.
- **Theme is `ey-light` base + `_brand.scss`.** Drive colors through CSS tokens; EY
  yellow is a sparse accent (`#F2C200`), never body text or large fills. See `design.md`.
- **`run_id` (UUID) is immutable.** Recalibration creates a new run; never mutate an
  existing one. Failed jobs keep their traceback in `error_message` — never swallow.
- **Don't break serialised model pickles** in MinIO — version new plugins instead.
- **Deletes are dependency-checked** (FK, no cascade): block with 409 + dep list, do
  not auto-cascade.
- **Auth & RBAC:** cookie-based revocable sessions (httpOnly access + refresh cookies, CSRF
  tokens). All `/api/*` routes except `/api/auth/login` and `/api/ping` require
  `@jwt_required()`. Fine-grained permissions use `@require_perm("domain:action")` from
  `api/auth/decorators.py` — 9 domains × `{read, write, execute}` (delete is folded into
  write). Roles are DB-managed in the `roles` table; the built-in `sysadmin` role (`["*"]`,
  `is_system=True`) cannot be deleted or renamed. The role registry is cached 5 min per
  process (use Redis in prod). `WTF_CSRF_ENABLED=False` is intentional (CSRF tokens are
  sent in a custom `X-CSRF-TOKEN` header, not via WTF forms). See `architecture.md` and
  `state_management.md` for full detail.
- **Never expose** MLflow UI or Celery Flower to users.
- **Git commits:** never add `Co-Authored-By` trailers. Only commit when I explicitly tell you to.
- **Branch management:** whenever fixing a bug or adding a new feature, if it requires a lot of changes, create a new branch to work on.

## 6. Additional Documentation

**`.claude/docs/`** — domain knowledge:
- [architecture.md](.claude/docs/architecture.md) — repo layout, backend/frontend
  structure, request lifecycle, core logic, model registry, run lifecycle, infra.
- [database_models.md](.claude/docs/database_models.md) — tables, the `kind` column,
  FK dependency chain, delete constraints.
- [state_management.md](.claude/docs/state_management.md) — Vuex store, JWT refresh
  flow, RBAC, progress polling.
- [design.md](.claude/docs/design.md) — theme architecture, tokens, UI principles,
  reference components, charts, logos.
- [conventions.md](.claude/docs/conventions.md) — Python & Vue code style / formatting.

**`.claude/skills/`** — reusable procedures:
- [frontend-design](.claude/skills/frontend-design/SKILL.md) — aesthetic direction,
  typography, and distinctive UI/visual design choices.
- [mcp-builder](.claude/skills/mcp-builder/SKILL.md) — building MCP servers (Python
  FastMCP / Node TypeScript SDK) that expose external APIs as tools.
- [skill-creator](.claude/skills/skill-creator/SKILL.md) — creating, editing, and
  evaluating Claude skills.
- [webapp-testing](.claude/skills/webapp-testing/SKILL.md) — Playwright-based testing
  and debugging of local web apps (screenshots, console/network logs).

**`.claude/bugs/`** — fixed-bug patterns (read before touching the same area):
- [fk-constraint-on-delete.md](.claude/bugs/fk-constraint-on-delete.md),
  [vmodel-ternary-compile-error.md](.claude/bugs/vmodel-ternary-compile-error.md),
  [detached-instance-in-celery-tasks.md](.claude/bugs/detached-instance-in-celery-tasks.md),
  [primevue-multiselect-filter-matchmode.md](.claude/bugs/primevue-multiselect-filter-matchmode.md)

> When you fix a bug, add a pattern file to `.claude/bugs/`. When you learn a reusable procedure, add it to `.claude/skills/`. Keep CLAUDE.md a pure index.
