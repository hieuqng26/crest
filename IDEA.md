I want to leverage my past project (the current one) for my new application.

## What should be kept
- Tech stack: **Vue 3** (PrimeVue + Vuex + Tailwind), Python/Flask, Docker
- UI layout (sidebar, theme)

## What can be changed
- Specific UI pages
- Workflow
- Anything better suited to the new application — propose it

## New application

A **banking-grade machine learning calibration platform** for quantitative analysts and risk modellers. It allows users to:

1. **Ingest data** — file upload (CSV/Excel/Parquet) or live query from a dedicated risk database.
2. **Configure models** — select from a registry of supervised and statistical ML models, parameterised via a structured config.
3. **Calibrate** — trigger async model fitting/estimation with progress tracking and logging.
4. **Evaluate** — backtesting, model diagnostics, statistical validation metrics, residual analysis — through a fully custom UI.
5. **Forecast** — visualize actual vs. predicted of target variables.
6. **Credit Risk Analysis** — use structured prediction outputs for downstream credit risk tasks (IFRS 9 ECL, PD/LGD, Credit Grade movements).

Deployed inside a bank's internal infrastructure. **Security, auditability, reproducibility, and statistical rigour are non-negotiable.** All experiment tracking, model versioning, and diagnostics are presented through the first-party **Vue UI** — no dependency on third-party tracking UIs (MLflow UI, Weights & Biases, etc.). A headless tracking backend (e.g. MLflow server) is acceptable as long as our UI is the sole user-facing surface.

## Scope of model coverage

Banks run multiple portfolios with heterogeneous data (financial / non-financial, numerical / categorical). The platform must cover:
- **Supervised classification** (e.g. PD scoring, grade transitions) — scikit-learn estimators
- **Time-series regression / forecasting** (e.g. macro factor projection, LGD trajectories) — statsmodels + sklearn
- **Statistical models** (GLMs, ARIMA, state-space, survival) — statsmodels

The model registry abstraction must handle all three families behind a uniform config + calibration + diagnostics interface.

## Next steps
1. **Cleanup**: remove any unused files
2. **Detailed PLAN.md**: backend architecture (storage layer, tracking schema, model registry abstraction, calibration job lifecycle, API surface), frontend page map and workflow (ingest → configure → calibrate → evaluate → forecast → credit-risk views), how models are stored / reused / recalibrated, any tech-stack additions (e.g. MinIO, pydantic for config validation).
3. **CLAUDE.md** from the PLAN — operational guidance for future sessions.
4. **Frontend**: build against dummy data / mock model.
5. **Backend**: API → model registry → integrate with realistic data.
