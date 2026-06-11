# Banking ML Calibration Platform — Architecture Plan

## 1. Overview

A banking-grade ML calibration platform for quantitative analysts and risk modellers.
Built on the existing Vue 3 + Flask + MSSQL + Redis + Docker stack.

**Workflow:** Ingest → Configure → Calibrate → Evaluate → Forecast → Credit Risk

---

## 2. AI Assistant Model Policy

- **Default model:** `claude-sonnet-4-6` (1M context) — use for all routine tasks (file edits, component scaffolding, API wiring, bug fixes).
- **Switch to `claude-opus-4-7`** for complex tasks: designing a new abstraction (e.g. model registry plugin interface), multi-file architectural refactors, statistical diagnostics logic, credit risk computation, or anything requiring deep reasoning across many files at once.
- If mid-task complexity warrants Opus, **stop and tell the user to switch** rather than proceeding on Sonnet and producing a shallow result.

---

## 3. What Is Kept (Unchanged)

| Asset | Rationale |
|---|---|
| Vue 3 + PrimeVue 3 + Vuex + Tailwind | Proven, already integrated |
| Flask + SQLAlchemy + Flask-JWT-Extended | Auth, RBAC, audit log all work |
| Redis + RQ workers | Async job pattern is reused as-is |
| MSSQL (live risk DB) + app DB | Risk DB is the "live query" data source |
| Layout: `AppLayout`, `AppTopbar`, `AppSidebar`, `AppMenu` | Shell kept; only menu items change |
| Auth views: Login, Access, Error, NotFound | No change needed |
| UAM + Audit Log views | Retained |
| Job model (`jobs`, `jobHistory` tables) | Reused for calibration jobs |
| `httpClient.js`, Vuex auth/job/file actions | Reused as-is |
| `socket.io-client` + Flask-SocketIO | Live progress events from worker |

---

## 4. What Is Removed (Cleanup)

| Path | Reason |
|---|---|
| `services/server/project/db_models/example_models.py` | ESG domain models, no longer relevant |
| `services/server/project/api/calculation/routes.py` (stub) | Replaced by new calibration blueprint |
| `services/server/project/core/__init__.py` (empty) | Will be populated by model registry |
| `services/client/src/views/Dashboard.vue` (empty) | Replaced by new Dashboard |
| All commented-out `docker-compose.debug.yml` worker blocks | Replaced by new worker topology |
| `geopy`, `maptiler`, `cartopy`, `rasterio`, `geopandas`, `h3`, `shapely`, `pyproj`, `contextily` in requirements.txt | Geo libs not needed |
| `plotly.js` frontend dep (heavy) | Keep `apexcharts` only; Plotly added only if residual plots need it |

---

## 4. Tech-Stack Additions

| Addition | Purpose |
|---|---|
| `pydantic>=2.4` (already listed) | Config schema validation for model registry |
| `mlflow` (headless server only) | Experiment + artifact tracking backend; UI is ours |
| `boto3` / `minio` | Artifact object storage (model pickles, diagnostics JSON) |
| `celery>=5.4` (already listed) | Replace RQ for async calibration; richer retry/chain semantics |
| `flower` (Celery monitor, internal only) | Ops visibility; not user-facing |
| `alembic` (via Flask-Migrate, already present) | New migration for calibration tables |

**No new frontend framework additions.** Existing `apexcharts`, `chart.js`, `plotly.js-dist`, PrimeVue DataTable cover all diagnostic widgets.

---

## 5. Backend Architecture

### 5.1 Directory Layout

```
services/server/project/
├── api/
│   ├── auth/           (keep)
│   ├── users/          (keep)
│   ├── roles/          (keep)
│   ├── auditlog/       (keep)
│   ├── jobs/           (keep — base job CRUD)
│   ├── files/          (keep — upload entry point)
│   ├── data/           (keep — live DB query)
│   ├── datasets/       NEW — dataset registry CRUD
│   ├── models/         NEW — model registry CRUD
│   ├── calibrations/   NEW — calibration job lifecycle
│   ├── evaluations/    NEW — diagnostics / metrics retrieval
│   └── forecasts/      NEW — prediction / forecast retrieval
├── core/
│   ├── model_registry/ NEW — BaseMLModel + plugin loader
│   ├── calibration/    NEW — job runner, MLflow logging
│   ├── diagnostics/    NEW — metric computation (AUC, KS, Gini, RMSE, MAE, etc.)
│   └── credit_risk/    NEW — IFRS 9 ECL, PD/LGD aggregation
├── db_models/
│   ├── job_models/     (keep)
│   ├── calibration_models.py  NEW
│   └── dataset_models.py      NEW
└── workers/
    └── tasks.py        NEW — Celery tasks (ingest, calibrate, evaluate)
```

### 5.2 Storage Layer

| Store | Contents |
|---|---|
| MSSQL app DB | Users, roles, audit log, jobs, datasets registry, model registry metadata, calibration run metadata |
| MSSQL risk DB | Live query source (read-only, via pyodbc; separate connection string) |
| MinIO / local volume | Raw uploaded files (CSV/Excel/Parquet), model artifacts (.pkl), diagnostics outputs (JSON) |
| Redis | Celery broker + result backend; SocketIO pub/sub for progress events |
| MLflow server (headless) | Experiment runs, metrics time series, param logging (accessed by backend only) |

### 5.3 Key DB Tables (New)

```sql
datasets
  id, name, description, source (upload|live_query), file_path, schema_json,
  row_count, created_by, created_at, status

model_configs
  id, name, family (classification|timeseries|statistical),
  algorithm, hyperparams_json, feature_cols_json, target_col,
  created_by, created_at

calibration_runs
  id, run_id (uuid), dataset_id FK, model_config_id FK,
  status (queued|running|success|failed), triggered_by,
  mlflow_run_id, artifact_path, started_at, finished_at,
  train_metrics_json, val_metrics_json, error_message

forecasts
  id, calibration_run_id FK, forecast_horizon, forecast_json,
  created_at
```

### 5.4 Model Registry Abstraction

```python
# project/core/model_registry/base.py
class BaseMLModel(ABC):
    family: str           # "classification" | "timeseries" | "statistical"
    algorithm: str        # e.g. "LogisticRegression"
    param_schema: type    # Pydantic model

    @abstractmethod
    def fit(self, X, y, params) -> None: ...

    @abstractmethod
    def predict(self, X) -> np.ndarray: ...

    @abstractmethod
    def diagnostics(self, X, y) -> dict: ...  # returns metric dict
```

Plugins registered via a `REGISTRY: dict[str, type[BaseMLModel]]` in `__init__.py`.
Config validated with Pydantic before the Celery task is dispatched.

**Initial plugins (Phase 2):**
- Classification: `LogisticRegression`, `RandomForest`, `GradientBoosting`, `LightGBM`
- Time-series: `ARIMA`, `ARIMAX`, `OLS`, `Ridge`
- Statistical: `GLM` (Binomial/Gaussian/Poisson), `ProportionalHazards` (Cox), `StateSpace`

### 5.5 Calibration Job Lifecycle

```
POST /api/calibrations/        → validate config → enqueue Celery task → return run_id
Celery task:
  1. load dataset from MinIO / risk DB
  2. feature prep
  3. model.fit(X_train, y_train, params)
  4. mlflow.log_params / log_metrics
  5. pickle → MinIO artifact store
  6. model.diagnostics(X_val, y_val) → store in calibration_runs.val_metrics_json
  7. emit SocketIO progress events (0% → 100%)
  8. update calibration_runs.status = "success"

GET  /api/calibrations/{run_id}        → run metadata + metrics
GET  /api/calibrations/{run_id}/diagnostics → full diagnostic JSON
GET  /api/calibrations/{run_id}/forecast    → actual vs predicted series
```

### 5.6 API Surface (New Endpoints)

```
# Datasets
GET  /api/datasets/
POST /api/datasets/upload         (file upload → MinIO → register)
POST /api/datasets/query          (live risk DB query → register)
GET  /api/datasets/{id}
DELETE /api/datasets/{id}

# Model registry
GET  /api/models/registry         (list available algorithms + param schemas)
GET  /api/models/configs
POST /api/models/configs
GET  /api/models/configs/{id}

# Calibrations
GET  /api/calibrations/
POST /api/calibrations/
GET  /api/calibrations/{run_id}
GET  /api/calibrations/{run_id}/diagnostics
GET  /api/calibrations/{run_id}/forecast
POST /api/calibrations/{run_id}/recalibrate

# Credit risk
POST /api/credit-risk/ecl         (IFRS 9 ECL from run output)
POST /api/credit-risk/pd-lgd      (PD/LGD term structure)
```

---

## 6. Frontend Page Map

```
/                           Home (splash, sign-in)
/auth/login                 Login
/dashboard                  Summary: recent runs, model performance KPIs

/ingest                     Ingest Hub
  /ingest/upload            File Upload (CSV/Excel/Parquet → dataset)
  /ingest/query             Live DB Query builder + preview
  /ingest/datasets          Dataset registry table

/configure                  Model Config Hub
  /configure/registry       Algorithm catalogue (families, param schemas)
  /configure/new            New model config form (Pydantic-driven)
  /configure/list           Saved configs

/calibrate                  Calibration Hub
  /calibrate/new            Launch run: pick dataset + config
  /calibrate/jobs           Run list (status, progress bars, ETA)
  /calibrate/:run_id        Live progress + log stream

/evaluate                   Evaluation Hub
  /evaluate/:run_id         Full diagnostics dashboard:
                              - Classification: ROC/AUC, KS, Gini, confusion matrix,
                                hosmer-lemeshow, calibration curve, feature importance
                              - Time-series: ACF/PACF, residual plots, MAPE/RMSE,
                                Ljung-Box, heteroscedasticity tests
                              - Statistical: coefficient table, p-values, VIF,
                                log-likelihood, AIC/BIC, deviance residuals

/forecast                   Forecast Hub
  /forecast/:run_id         Actual vs Predicted chart + forecast horizon slider

/credit-risk                Credit Risk Hub
  /credit-risk/ecl          IFRS 9 ECL dashboard (PD×LGD×EAD, stage buckets)
  /credit-risk/pd-lgd       PD/LGD term structure visualisation
  /credit-risk/transitions  Credit grade transition matrix heatmap

/uam                        User Access Management (unchanged)
/log                        Audit Logs (unchanged)
```

### Sidebar Menu Groups

```
Data         → Ingest Hub (upload, query, datasets)
Models       → Configure Hub (registry, configs)
Calibration  → Calibrate Hub (new run, job list)
Evaluation   → Evaluate Hub
Forecast     → Forecast Hub
Credit Risk  → Credit Risk Hub
System       → UAM, Audit Logs
```

---

## 7. How Models Are Stored / Reused / Recalibrated

1. **Stored**: Celery task pickles the fitted estimator to MinIO at `artifacts/{run_id}/model.pkl`. Metadata (MLflow run ID, artifact path) recorded in `calibration_runs`.
2. **Reused**: Any `GET /api/calibrations/{run_id}/forecast` loads the pickle from MinIO, runs `model.predict(X_new)`.
3. **Recalibrated**: `POST /api/calibrations/{run_id}/recalibrate` clones the model config, accepts an optional new dataset ID, enqueues a fresh Celery task. Previous run remains immutable in the audit trail.
4. **Versioning**: Each run has a unique `run_id` (UUID). MLflow tracks all runs under an experiment named after the model config. The UI shows a run comparison table.

---

## 8. Build Sequence (Steps 4–5 from IDEA.md)

### Phase 1 — Cleanup & Scaffold (current)
- [x] Write PLAN.md (this file)
- [x] Write CLAUDE.md
- [x] Remove ESG-specific domain models and dead stubs
- [x] Add new DB tables via Alembic migration
- [x] Update `requirements.txt` (add mlflow, minio, lightgbm; remove geo libs)
- [x] Update `docker-compose.debug.yml` (add MinIO, Celery worker, MLflow server)

### Phase 2 — Frontend (dummy data)
- [ ] Update router + AppMenu with new page map
- [ ] Ingest views (upload + dataset table)
- [ ] Configure views (registry browser + config form)
- [ ] Calibrate views (launch form + job list + live progress)
- [ ] Evaluate views (diagnostic widget layout — mock data)
- [ ] Forecast view (actual vs predicted chart — mock data)
- [ ] Credit Risk views (ECL dashboard — mock data)

### Phase 3 — Backend API
- [ ] `datasets/` blueprint + MinIO upload
- [ ] `models/` blueprint + registry endpoint
- [ ] `calibrations/` blueprint + Celery task
- [ ] `evaluations/` diagnostics computation
- [ ] `forecasts/` endpoint
- [ ] `credit_risk/` ECL/PD-LGD logic

### Phase 4 — Integration
- [ ] Wire frontend to real API (remove mock data)
- [ ] SocketIO live progress events
- [ ] MLflow headless integration
- [ ] End-to-end test with sample PD dataset

---

## 9. Security & Auditability Requirements

- All calibration runs logged in `audit_log` (who triggered, when, config snapshot).
- Model artifacts are immutable once written; recalibration creates a new run.
- RBAC: `analyst` role can trigger calibration; `viewer` role is read-only.
- No MLflow UI exposed to users — all diagnostics served through our API.
- CSRF disabled for API (JWT in headers); re-enable for any future form-based flows.
- All secrets in `.env` files; never committed (`.gitignore` already covers `env/`).
