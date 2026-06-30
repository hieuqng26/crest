# CREST — Production-Readiness & Tech-Debt Roadmap

> **Status:** Draft audit, 2026-06-21. Owner: TBD.
> **Scope:** Full stack — Flask/Celery backend, Vue/PrimeVue frontend, MSSQL/MinIO/Redis infra, security, testing/CI, observability.
> **Framing:** Long-term tech-debt roadmap. Items are prioritized P0→P3 by *severity*, but there is no hard deadline — chip away top-down. P0 items are correctness/security issues you should not ship to any real user without fixing.

## How to read this

Each item has: **[AREA] Title — Impact / Effort**, the **evidence** (file references), and the **fix**.
Effort is a rough order of magnitude: `S` ≈ ≤0.5d, `M` ≈ 1–2d, `L` ≈ 3–5d, `XL` ≈ 1–2wk.

Phases are *severity tiers*, not a strict schedule:

| Phase | Theme | Why it's here |
|-------|-------|---------------|
| **P0** | Security & correctness | Data exposure, privilege escalation, or simply broken in prod. |
| **P1** | Scale & performance | Works today at demo scale; degrades or falls over as data grows. |
| **P2** | Maintainability & structure | Slows every future change; raises bug risk. |
| **P3** | Testing, CI/CD, observability | The safety net that lets you do P0–P2 *confidently*. Start a slice of this early. |

> **Recommended first move:** land a thin slice of **P3-T1/T2** (a pytest harness + CI that runs it) *before* the P1/P2 refactors, so you can refactor without fear. P0 security fixes are small and should go in regardless.

---

## P0 — Security & correctness (do first)

### [SEC] S1 — Hardcoded secrets & credentials committed to the repo — High / S
**Evidence:**
- `services/server/project/config.py:18` `SECRET_KEY` default, `:27` `JWT_SECRET_KEY` default (real-looking hex), `:89/:161` DB password `Ey@2026!`.
- `docker-compose.prod.yml`: Redis `REDIS_PASSWORD=Ey@2026!`, MSSQL `SA_PASSWORD=Supersecret@123!`, APM `SECRET_TOKEN=supersecret` (`config.py:124/198`).
- `services/client/.env` is tracked in git (`git ls-files`), unlike `env/.env.*` which are correctly gitignored.

**Why it matters:** anyone with repo access has prod JWT-signing keys and DB/Redis passwords. A leaked `JWT_SECRET_KEY` lets an attacker forge tokens for any user.

**Fix:**
1. Rotate every committed secret (JWT key, DB, Redis, APM).
2. Remove defaults from `config.py`; in `ProductionConfig`, **fail fast** if a required secret env var is missing (don't fall back to a baked-in value).
3. Move compose passwords to `env/.env.prod` (already gitignored) via `${VAR}` interpolation.
4. Remove `services/client/.env` from tracking; ship `.env.example` only.
5. Consider `git filter-repo` to purge secrets from history (or treat all rotated).

### [SEC] S2 — RBAC is not enforced on user-management or compute/data endpoints — **RESOLVED** ✓
**Resolved by:** `AUTH_RBAC_REBUILD_PLAN.md` (Tasks 1–17, branch `feature/auth-rbac-rebuild`).

**What was built:**
- Fine-grained permission catalog (9 domains × `{read,write,execute}`) in `api/auth/permissions.py`.
- `@require_perm("domain:action")` decorator applied to every endpoint across all blueprints
  (datasets, model_configs, calibrations, evaluations, forecasts, forecast_runs, credit_risk,
  auditlog, users, roles).
- DB-managed roles (`roles` table) with a 5-min cached registry; role edits take effect without
  re-login.
- Built-in `sysadmin` role (wildcard `["*"]`, `is_system=True`) is the lockout-recovery path and
  cannot be deleted/renamed.
- Legacy `roles_required` and the `active_session` table removed; Alembic migration applied.
- Frontend: `v-can` directive, Vuex `can(perm)` getter, router `requiresPerm` guard, Role Management
  CRUD page (`/admin/role-management`).
- Single-session enforcement + revocable httpOnly cookie sessions (`user_sessions` table).

### [SEC] S3 — `/api/datasets/query` runs arbitrary user SQL — High / M
**Evidence:** `api/datasets/routes.py` `query_dataset()` takes a raw `sql` string and only rejects it if the first word isn't `SELECT`/`WITH`, then `pd.read_sql(sql, conn)` against `RISK_DB_CONN_STR`.

**Why it matters:** a `SELECT` can still read every table the connection can see (`information_schema`, other schemas, cross-DB), enabling data exfiltration. First-word filtering is not a security boundary. No RBAC either (see S2).

**Fix (pick one, in order of preference):**
1. Replace free-form SQL with a **parameterized, allowlisted** query catalog (named queries + bound params).
2. If ad-hoc SQL is a hard requirement, run it under a dedicated **least-privilege, read-only** DB login scoped to a single schema/views, enforce a statement timeout, gate behind `analyst`+ RBAC, and log every query to the audit trail.

### [BUG] C1 — Live KMV/ECL endpoints read from local disk; uploads & workers use MinIO — High / M
**Evidence:** uploads go to MinIO (`datasets/routes.py` `upload_dataset` → `storage.upload_bytes`, `file_path = "{bucket}/uploads/..."`). Workers read from MinIO (`workers/tasks.py:249` `storage.download_bytes(...)`). But the synchronous credit-risk endpoints read from the **local filesystem**: `credit_risk/routes.py:74-80` and `:570-575` build `os.path.join(DATA_STORE, dataset.file_path)` and call `_read_dataset(path)` (`:553`).

**Why it matters:** `file_path` is a MinIO key (`mst-artifacts/uploads/...`), so `os.path.join(DATA_STORE, ...)` points at a path that doesn't exist on disk → `GET /credit-risk/clients` and the inline `/kmv` `/ecl` endpoints fail for any real (non-`mock`) dataset. It's latent because the demo path uses `mock=true`.

**Fix:** route *all* dataset reads through `core/storage.py`. Delete the `DATA_STORE`/`os.path.join` branch in `credit_risk/routes.py`; reuse a single `load_dataframe(file_path)` helper (see M2).

### [SEC] S4 — Unencrypted DB connection & token-in-localStorage — Medium / S
**Evidence:**
- `config.py:97/169` ODBC string sets `Encrypt=no; TrustServerCertificate=yes` → MSSQL traffic is plaintext.
- ~~Frontend persists the JWT to `localStorage` via `vuex-persistedstate`~~ — **half resolved:** the
  auth rebuild (Task 12–13) switched to httpOnly cookies with no `localStorage` persistence.
  `currentUser` and `permissions` are re-populated from `/auth/me` on every load, not from storage.
  Tokens are never accessible to JavaScript. The `localStorage` XSS vector is closed.

**Remaining:** set `Encrypt=yes` on the MSSQL ODBC string with a proper cert chain (or
`TrustServerCertificate` only inside a trusted network). The DB-in-plaintext issue is unchanged.

### [SEC] S5 — CORS handler can 500; CORS configured twice — Medium / S
**Note:** the `CORS_ORIGIN` null-guard fix (`os.getenv("CORS_ORIGIN", "")`) landed in **Task 3** of the auth-RBAC rebuild, preventing the `AttributeError` 500 on startup. The dual-CORS-mechanism cleanup (prefer `flask-cors` over the manual `after_request`) is still pending.

**Evidence:** `__init__.py:149-150` `os.getenv("CORS_ORIGIN").split(",")` → `AttributeError` if `CORS_ORIGIN` is unset (every request). Also `flask-cors` is initialized with an empty origins list (`:73-77`) and then a manual `after_request` re-implements CORS (`:147`) — two sources of truth.

**Remaining fix:** pick **one** CORS mechanism (prefer `flask-cors` driven by an env allowlist) and remove the manual `after_request` duplication.

---

## P1 — Scale & performance

### [DB] P1a — Missing indexes on foreign keys & ordering columns — High / S
**Evidence:** indexed today: `*_run_logs.run_id`, `credit_risk_results.run_id/client_id`, a few cascade FKs. **Not** indexed: `calibration_runs.dataset_id` / `.model_config_id` / `.triggered_by` (`calibration_models.py:83-91`), `forecasts.calibration_run_id` (`:172`), `forecast_runs.calibration_run_id` / `.dataset_id` (`forecast_models.py:12-17`), `credit_risk_runs.dataset_id` (`credit_models.py:49`), `credit_risk_run_forecast_inputs.forecast_run_id` (`:35`), and the `created_at` columns used to sort every list endpoint.

**Fix:** one Alembic migration adding indexes on all FK columns + the `created_at` sort keys. Cheap, high payoff as run/result counts grow.

### [PERF] P1b — N+1 queries in list/detail endpoints — Medium / M
**Evidence:**
- `credit_risk/routes.py:218-228` `list_runs`: `Dataset.query.get(r.dataset_id)` inside the loop (one query per run).
- `:299-310` `get_active_run` and `:440-451` `get_run`: load **all** `CreditRiskResult` rows just to compute `sorted({r.client_id ...})`.
- Same N+1 shape is likely in other domains' list routes (calibrations, forecast_runs) — audit them together.

**Fix:** `join`/`selectinload` the dataset name in `list_runs`; replace the "load all results" pattern with `session.query(CreditRiskResult.client_id).filter_by(...).distinct()`.

### [PERF] P1c — No pagination; list endpoints return whole tables — Medium / M
**Evidence:** `.all()` with no limit: `datasets/routes.py` `list_datasets`, `credit_risk/routes.py` `list_runs`, `get_run_logs` (`:454`), and the audit-log routes. Logs and results grow unbounded.

**Fix:** standard server-side pagination (`limit`/`offset` or keyset on `id`) returning `{rows, total, page}`. `get_run_results` already does this (`:389`) — generalize that pattern into a shared helper and apply everywhere. Wire the frontend `PaginatedDataTable.vue` to real server paging.

### [PERF] P1d — Heavy file parsing inside request handlers — Medium / M
**Evidence:** `credit_risk/routes.py` `get_clients` and `_load_client_data` download+parse an entire dataset with pandas **synchronously in the request**. Gunicorn `timeout=60` (`gunicorn_config.py:30`) — a large CSV/XLSX parse can blow the timeout and kill the worker.

**Fix:** precompute and store the client list + schema **at upload time** (already parsing the file there — `datasets/routes.py` `upload_dataset` reads `df` and stores `schema_json`; also store distinct `client_id`s / a small manifest). Serve those from the DB/Redis cache (`flask-caching` is already configured) instead of re-reading MinIO per request.

### [PERF] P1e — Celery worker setup is not production-tuned — High / M
**Evidence:**
- Every task calls `_make_flask_app()` → `create_app()` (`tasks.py:52,203,519,682`), rebuilding the Flask app, DB engine, JWT, cache, and blueprint registration **on every task invocation**.
- `workers/__init__.py`: single `default` queue, default prefork pool, **no** `task_time_limit`/`task_soft_time_limit`, **no** `worker_max_tasks_per_child`. `task_acks_late=True` *without* `task_reject_on_worker_lost` → a worker crash **redelivers** a long ML job that may have partially written results (double-run risk).
- `entrypoint.sh` runs the worker with no `--concurrency`; debug uses `--pool=solo`.

**Fix:**
1. Build the Flask app **once per worker process** (Celery `worker_process_init` signal or a module-level app), reuse its app context — removes per-task engine churn.
2. Add `task_soft_time_limit`/`task_time_limit`, `worker_max_tasks_per_child` (caps memory leaks from numpy/pandas), and `worker_prefetch_multiplier=1` for long tasks.
3. Make runs **idempotent** (clear prior partial results on start — `rerun_run` already does this) so `acks_late` redelivery is safe, or set `task_reject_on_worker_lost` deliberately.
4. Split queues (e.g. `calibration` vs `credit` vs `default`) so a long credit run doesn't starve quick jobs.

### [PERF] P1f — Gunicorn GC hack & preload pitfalls — Low / S
**Evidence:** `gunicorn_config.py` disables GC per request and calls `gc.collect()` after **every** request (`pre_request`/`post_request`) — a full collection per request is expensive and usually counterproductive. `preload_app=True` with a pre-fork SQLAlchemy engine risks shared connections across workers (mitigated by `pool_pre_ping`, but worth verifying the engine is created post-fork).

**Fix:** drop the per-request `gc.collect()`; if you want the "disable GC" trick, do it once at boot, not per request. Confirm the DB engine is initialized after fork (Flask-SQLAlchemy with the app factory generally is, but verify under `preload_app`).

---

## P2 — Maintainability & structure

### [REFACTOR] M1 — `workers/tasks.py` (929 lines) has heavy duplication — Medium / L
**Evidence:** the CSV/XLSX/Parquet load block is copy-pasted **4×** (`tasks.py:252-259, 284-293, 551-558, 727-734`); `_coerce` is defined twice (`:422, :596`); three near-identical progress writers (`_write_progress`, `_write_forecast_progress`, `_cr_log`); three tasks repeat the same "load scalars → mark running → try/persist/except mark failed" skeleton.

**Fix:** extract `core/io.py` (`load_dataframe(file_path) -> DataFrame`, `coerce_cell`), a single `RunProgress` helper parameterized by run-model, and a `@run_task` context manager that handles the running/success/failed lifecycle. Target: each task body becomes the *unique* logic only. Do this **after** P3-T1 gives you coverage on the quant outputs.

### [REFACTOR] M2 — Three divergent dataset readers — Low / S
**Evidence:** `credit_risk/routes.py:553` `_read_dataset(path)` (local disk), `datasets/routes.py:25` `_read_dataframe(bytes, ext)`, and the inline blocks in `tasks.py`. Same job, three implementations, different sources (disk vs MinIO) — root cause of bug **C1**.

**Fix:** one `core/io.load_dataframe(file_path)` that always goes through `core/storage.py`. Delete the others. (Folds into M1.)

### [REFACTOR] M3 — Circular-import pressure from `project/__init__.py` — Medium / M
**Evidence:** `db`, `app_session`, `cache`, `DATA_STORE` all live in `project/__init__.py`, forcing **inline imports inside functions** throughout (`tasks.py`, every route does `from project import app_session` locally). This is a code smell that makes refactoring and testing harder.

**Fix:** move extensions to a `project/extensions.py` (`db = SQLAlchemy()`, `cache`, `bcrypt`, `app_session`) imported by both the factory and modules. Lets you use top-level imports and import models/services without dragging in the whole app.

### [REFACTOR] M4 — Hand-maintained `to_dict()` serializers — Low / M
**Evidence:** every model has a manual `to_dict()` that must be kept in sync with columns (called all over the routes; noted as a footgun in `database_models.md`).

**Fix:** introduce a serialization layer — a `SerializerMixin` that reflects columns, or Pydantic/marshmallow response schemas (Pydantic 2 is already a dependency). Bonus: typed API responses + a path toward OpenAPI docs.

### [CLEANUP] M5 — Dead/mock code on the production API surface — Low / S
**Evidence:** `credit_risk/routes.py:484-547` `compute_ecl_v1` / `compute_pd_lgd_v1` "v1 dummies (retained)"; `mock=true` branches return fabricated data (`:59, :110, :174`); frontend ships `views/*/mock/` folders (`configure/mock`, `ingest/mock`, `evaluate/mock`, `calibrate/mock`).

**Fix:** delete the v1 dummies, and put any remaining mock paths behind an explicit `DEMO_MODE` flag (off in prod) rather than a request-controlled `mock` boolean.

### [CONFIG] M6 — Config duplication & doc drift — Low / S
**Evidence:** `DevelopmentConfig` and `ProductionConfig` (`config.py:60-203`) are ~90% identical copy-paste. ODBC driver mismatch: code uses **Driver 18** (`config.py:92/164`, `Dockerfile.prod` installs `msodbcsql18`) but `architecture.md:103` / `CLAUDE.md:26` say **Driver 17**.

**Fix:** factor shared config into a base and override only deltas. Fix the doc to say Driver 18 (or align everything on one version).

---

## P3 — Testing, CI/CD, observability (the safety net)

### [TEST] T1 — Almost no automated tests — High / L
**Evidence:** one backend test file (`services/server/tests/test_credit_risk.py`); zero frontend tests. The S2 privilege-escalation bug is a direct symptom of no endpoint-level tests.

**Fix (incremental):**
1. **Auth/RBAC tests first** — assert every mutating endpoint rejects under-privileged roles (would have caught S2).
2. **Quant golden tests** — pin `run_kmv`/`compute_ecl` outputs on a fixed fixture so the M1/M2 refactors are provably behavior-preserving.
3. **API smoke tests** with `pytest-flask` (already a dep) against the SQLite `TestingConfig`.
4. **Frontend:** Vitest + Testing Library for stores/composables (start with the `httpClient` refresh logic and a `usePolling` composable).

### [CI] T2 — No CI pipeline — High / M
**Evidence:** no CI config in the repo. `ruff` is the agreed linter (CLAUDE.md §3) but nothing enforces it; `pytest.ini`/`coverage` deps exist but aren't run automatically.

**Fix:** add CI (GitHub Actions or equivalent) running on PRs: `ruff check`/`ruff format --check`, backend `pytest --cov`, frontend `npm run build` + `vitest`, and a dependency/secret scan (e.g. `pip-audit`, `npm audit`, `gitleaks`). Block merge on red.

### [OBS] T3 — Health checks & error tracking — Medium / M
**Evidence:** only `/api/ping` returns `pong` (`__init__.py:143`) — no readiness check for DB/Redis/MinIO. APM is configured but with a hardcoded token (S1). Errors land in logs but there's no aggregation/alerting.

**Fix:** add `/api/health` that verifies DB, Redis, and MinIO connectivity (for orchestrator readiness/liveness probes). Wire APM/error tracking with a real token from env. Add Celery task failure alerting.

### [FE] T4 — Frontend structure & polling — Medium / M
**Evidence:** several 700+ line views (`Configurations.vue` 751, `CreditRiskRunView.vue` 726, `ForecastRunView.vue` 704, `PaginatedDataTable.vue` 761). Polling is hand-rolled with `setInterval` in **every** run/jobs view (`ForecastRunView.vue:105`, `ForecastJobs.vue:34`, `CalibrateRun.vue:23`, `ProgressTab.vue:44`, `CreditRiskJobs.vue`, …) — duplicated start/stop/cleanup logic, easy to leak timers.

**Fix:** extract a `usePolling(fn, { interval, until })` composable (handles visibility-pause, terminal-state stop, and unmount cleanup) and adopt it everywhere. Break the largest views into smaller components. Confirm every `setInterval` is cleared on unmount to avoid timer/memory leaks.

---

## Quick wins (high value, ≤0.5d each)

1. **S1** — strip secret defaults from `config.py`; fail fast in prod if unset.
2. ~~**S2**~~ — resolved by auth-RBAC rebuild.
3. ~~**S5** (CORS null-guard)~~ — null-guard fixed in auth-RBAC Task 3; dual-mechanism dedup still pending.
4. **P1a** — single migration adding the missing FK/`created_at` indexes.
5. **M5** — delete the `v1` dummy credit-risk endpoints.
6. **P1b** — swap the two "load all results to get distinct client_ids" spots for a `.distinct()` query.
7. **M6** — fix the ODBC Driver 17→18 doc drift.

## Suggested sequencing

0. **Auth/RBAC rebuild (DONE):** `AUTH_RBAC_REBUILD_PLAN.md` (Tasks 1–18, branch
   `feature/auth-rbac-rebuild`) — resolves S2 fully; closes the `localStorage` half of S4;
   patches the CORS null-guard from S5. This runs *before* the P0 security pass below.
1. **Week 0:** Quick wins above + stand up CI skeleton running `ruff` (T2).
2. **P0 security pass:** S1, S3, S4 (DB encryption), S5 (CORS dedup), C1 (each is S/M).
   S2 is resolved; add regression tests (T1.1) to lock it in.
3. **Safety net:** quant golden tests (T1.2) — prerequisite for the refactors.
4. **P1 scale pass:** indexes (P1a) → N+1/pagination (P1b/P1c) → Celery tuning (P1e) → request-time parsing (P1d).
5. **P2 refactor pass:** `extensions.py` (M3) → unify dataset IO (M2) → split `tasks.py` (M1) → serializers (M4).
6. **Ongoing:** frontend composables/component split (T4), health checks & APM (T3).

## Out of scope / explicitly *not* doing now

- PrimeVue v3→v4 upgrade (pinned intentionally; needs a full audit — CLAUDE.md §5).
- Reintroducing SocketIO (removed on purpose; DB-polling is the chosen model).
- Rewriting the quant core — KMV/ECL math is the asset; we only refactor its *plumbing*, guarded by golden tests.
