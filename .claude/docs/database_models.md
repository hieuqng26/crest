# Database Models

SQLAlchemy ORM in `services/server/project/db_models/`. All models subclass
`DBBaseModel` (`base_model.py`). Each table change needs an Alembic migration
(`.claude/skills/add-db-migration.md`).

## Tables & key columns

### `calibration_models.py`
- **`datasets`** — uploaded files. `created_by`→users.email, `status` (default `ready`),
  **`kind`** ∈ `calibration` | `credit` | `forecast` (default `calibration`).
  The `kind` column gates which dropdowns a dataset appears in (New Calibration /
  New Analysis / New Forecast filter by kind). `file_path` points into MinIO.
- **`model_configs`** — algorithm + hyperparameter config. `created_by`→users.email.
- **`calibration_runs`** — one training run. Immutable `run_id` (UUID, unique),
  `dataset_id`→datasets, `model_config_id`→model_configs, `status`
  (`queued`/`running`/`success`/`failed`), `val_metrics_json`, `error_message`,
  `triggered_by`→users.email.
- **`calibration_run_logs`** — `run_id`→calibration_runs.run_id, level/message/ts.

### `forecast_models.py`
- **`forecast_runs`** — applies a calibrated model to a forecast dataset. `run_id`
  (UUID), `calibration_run_id`→calibration_runs.id, `dataset_id`→datasets, `status`.
- **`forecast_run_results`** — `forecast_run_id`→forecast_runs.id **ON DELETE CASCADE**.
  Per-client/per-year predictions.
- **`forecast_run_logs`** — `run_id` (string, indexed; no FK).

### `credit_models.py`
- **`pd_ratings`** — static lookup: credit `rating` → PD/LGD curve. Used by KMV.
- **`credit_risk_runs`** — `run_id` (UUID), `dataset_id`→datasets, `status`, params
  (exposure, discount_rate, lifetime_horizon).
- **`credit_risk_run_forecast_inputs`** — join: `credit_risk_run_id`→credit_risk_runs.id
  **ON DELETE CASCADE**, `forecast_run_id`→forecast_runs.id. Maps the 3 KMV inputs
  (total_assets, short_term_debts, long_term_debts) to forecast runs.
- **`credit_risk_results`** — `run_id`→credit_risk_runs.run_id. Per-client PD/LGD/ECL.
- **`credit_risk_run_logs`** — `run_id`→credit_risk_runs.run_id.

## Dependency chain (matters for deletes)

```
datasets ──< calibration_runs ──< forecast_runs ──< credit_risk_run_forecast_inputs >── credit_risk_runs
              (model_configs)        │                                                       │
                                     └──< forecast_run_results (CASCADE)                     └──< credit_risk_results / logs
```

**FK delete constraints (caused real 500s — see `.claude/bugs/fk-constraint-on-delete.md`):**
- A `calibration_run` cannot be deleted while a `forecast_run` references it
  (`forecast_runs.calibration_run_id` has no cascade).
- A `forecast_run` cannot be deleted while a `credit_risk_run` references it via
  `credit_risk_run_forecast_inputs.forecast_run_id` (no cascade on that column).
- Always pre-check references and block with a clear 409 + dependency list rather
  than letting the DB raise. Use the pattern in `.claude/skills/delete-with-refs.md`.

## Conventions
- Runs carry an immutable UUID `run_id` (string) plus the integer PK `id`. FKs from
  child run-tables point at `id`; cross-domain references and logs key off `run_id`.
- Every model has a `to_dict()` (or similar) serializer used by routes — keep it in
  sync when adding columns.
