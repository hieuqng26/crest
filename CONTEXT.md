# MST Platform — Session Context

## What this is
Banking-grade ML calibration platform for quants and risk modellers.
Workflow: **Ingest → Configure → Calibrate → Evaluate → Forecast → Credit Risk**

See `PLAN.md` for full architecture, `CLAUDE.md` for conventions and UI rules, `ISSUES.md` for known open issues.

---

## Stack
- **Frontend:** Vue 3 (`<script setup>`), PrimeVue 3 (pinned — do not upgrade), Vuex 4, Vue Router 4, Tailwind 3, Vite, chart.js, socket.io-client
- **Backend:** Flask 3, SQLAlchemy 3, Flask-JWT-Extended, Celery 5, Flask-SocketIO
- **Storage:** MSSQL (app DB + read-only risk DB), MinIO (files + model artifacts), Redis (Celery broker)
- **ML tracking:** MLflow headless server (internal only — never expose UI)
- **Config validation:** Pydantic v2

---

## Current phase: Phase 4 complete (integration)

### Phase 3 backend — all implemented
| Blueprint | Prefix | Status |
|---|---|---|
| `datasets` | `/api/datasets/` | ✅ list, upload (MinIO), query (risk DB), get, rows (paginated), delete |
| `model_configs` | `/api/model-configs/` | ✅ registry, list, get, create |
| `calibrations` | `/api/calibrations/` | ✅ list, create, get, diagnostics, forecast, recalibrate |
| `evaluations` | `/api/evaluations/` | ✅ proxy to val_metrics_json |
| `forecasts` | `/api/forecasts/` | ✅ Forecast rows |
| `credit_risk` | `/api/credit-risk/` | ✅ ECL (PD×LGD×EAD), PD/LGD term structure |
| `auth / users / roles / auditlog` | various | ✅ unchanged |

**Celery task** `run_calibration(run_id)` in `workers/tasks.py`:
load dataset from MinIO → train/val split → optional scaler → `plugin.fit()` → MLflow log → pickle to MinIO → `classification_diagnostics()` → SocketIO progress events → DB update

**Model plugins** (`core/model_registry/plugins/`): `LogisticRegression`, `GradientBoosting`, `ARIMA`, `Ridge`, `GLM_Binomial`

**Shared diagnostics** (`core/model_registry/diagnostics.py`): AUC-ROC, KS, Gini, confusion matrix, calibration curve, Hosmer-Lemeshow, feature importance

### Phase 4 frontend wiring — all implemented
| Module | What changed |
|---|---|
| `src/api/` | Added `datasetsAPI.js`, `modelConfigsAPI.js`, `calibrationsAPI.js` |
| `datasetsStore.js` | `fetchDatasets()` → `GET /api/datasets/`; upload/query call real API |
| `configsStore.js` | `fetchConfigs()` → list + registry in parallel; `duplicateConfig` uses real POST |
| `Datasets.vue` | `onMounted(fetchDatasets)`; upload uses `datasetsAPI.upload` (FormData) |
| `DatasetView.vue` | `loadRows()` calls `datasetsAPI.rows()` with offset/limit/sort/filter |
| `Configurations.vue` | `onMounted(fetchConfigs)`; save uses `modelConfigsAPI.create` |
| `Models.vue` | `registry` is now reactive ref; default selection seeded via `watch`; null-guard on template |
| `CalibrateNew.vue` | `launch()` POSTs `calibrationsAPI.create`; `onMounted` seeds both stores |
| `CalibrateJobs.vue` | `onMounted` fetches from API; cancel/duplicate call real endpoints |
| `CalibrateRun.vue` | Async `getRun`; 3 s polling while running/queued; null-guard while loading |
| `ProgressTab.vue` | Mock ticker removed; listens on `socket.on('calibration_progress')` filtered by `run_id` |
| `runUtils.js` | `getRun` calls `calibrationsAPI.get`; fallback skeleton for not-yet-persisted runs |

---

## Frontend page map (current routes)
| Route | Component |
|---|---|
| `/datasets` | `views/ingest/Datasets.vue` |
| `/datasets/:id` | `views/ingest/DatasetView.vue` |
| `/models` | `views/configure/Models.vue` (Algorithm Catalog) |
| `/configurations` | `views/configure/Configurations.vue` |
| `/calibrate/new` | `views/calibrate/CalibrateNew.vue` |
| `/calibrate/jobs` | `views/calibrate/CalibrateJobs.vue` |
| `/calibrate/:run_id` | `views/calibrate/CalibrateRun.vue` — tabs: Overview · Progress · Diagnostics · Forecast |
| `/evaluate/:run_id` | `views/evaluate/EvaluateRedirect.vue` → redirects to `/calibrate/:id?tab=diagnostics` |
| `/forecast/:run_id` | `views/forecast/ForecastRedirect.vue` → redirects to `/calibrate/:id?tab=forecast` |
| `/credit-risk/ecl` | `views/credit_risk/CreditRiskECL.vue` |
| `/credit-risk/pd-lgd` | `views/credit_risk/CreditRiskPdLgd.vue` |
| `/uam`, `/log` | UAM + Audit Log (unchanged) |

---

## Key file locations
```
services/client/src/
  api/                datasetsAPI.js · modelConfigsAPI.js · calibrationsAPI.js · httpClient.js · socket.js
  views/calibrate/    CalibrateJobs.vue · CalibrateNew.vue · CalibrateRun.vue · runUtils.js
                      runTabs/  OverviewTab · ProgressTab · DiagnosticsTab · ForecastTab
  views/ingest/       Datasets.vue · DatasetView.vue · datasetsStore.js
  views/configure/    Models.vue · Configurations.vue · configsStore.js

services/server/project/
  api/datasets/routes.py          list · upload · query · get · rows · delete
  api/model_configs/routes.py     registry · list · get · create
  api/calibrations/routes.py      list · create · get · diagnostics · forecast · recalibrate
  api/credit_risk/routes.py       ecl · pd-lgd
  core/model_registry/            base.py · __init__.py (REGISTRY) · diagnostics.py
  core/model_registry/plugins/    logistic_regression · gradient_boosting · arima · ridge · glm_binomial
  core/storage.py                 MinIO client (upload_bytes · download_bytes)
  workers/tasks.py                run_calibration Celery task
  db_models/calibration_models.py Dataset · ModelConfig · CalibrationRun · Forecast

test_data/
  generate_test_data.py           generates 4 CSVs
  pd_corporate_2024.csv           300 rows · target: default_flag
  pd_retail_mortgage.csv          250 rows · target: default_flag
  lgd_dataset.csv                 200 rows · target: lgd
  macro_quarterly.csv             48 rows  · target: pd_rate (time-series)
```

---

## DB tables (app MSSQL)
`users` · `roles` · `audit_log` · `active_sessions` — unchanged  
`datasets` — id, name, source, file_path (MinIO key), schema_json, row_count, created_by, status  
`model_configs` — id, name, family, algorithm, hyperparams_json, feature_cols_json, target_col, created_by  
`calibration_runs` — id, run_id (UUID), dataset_id FK, model_config_id FK, status, triggered_by, mlflow_run_id, artifact_path, started_at, finished_at, train_metrics_json, val_metrics_json, error_message  
`forecasts` — id, calibration_run_id FK, forecast_horizon, forecast_json

---

## Deleted (ESG-era, no longer in codebase)
`api/jobs/` · `api/files/` · `api/data/` · `sftp.py` · `db_models/__init__.py` (seeder) · `db_models/job_models/` · `push_sftp.py`  
Frontend: `jobAPI.js` · `fileAPI.js` · `dataAPI.js` · `jobActions.js` · `fileActions.js` · `dataActions.js`

---

## Open issues
See `ISSUES.md`.  
**ISSUE-001:** Large file uploads block Flask worker; row pagination downloads full file from MinIO before slicing. Fix: streaming upload + Parquet caching or MSSQL staging table.

---

## What's next (Phase 5 candidates)
- Dashboard page (recent runs, KPI summary across all calibrations)
- Credit Risk Transitions page (`/credit-risk/transitions`)
- Full RBAC enforcement on frontend routes
- Replace polling in `CalibrateRun.vue` with SocketIO-driven status updates
- Add `DELETE /api/calibrations/<run_id>` backend endpoint (currently client-side only)
- Alembic migration to drop legacy `jobs` / `jobHistory` tables from MSSQL
