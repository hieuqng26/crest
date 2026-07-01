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
  - `seg_sector_overrides_json` — sparse per-sector override of
    segmentation settings/model/features: `{sector: {split_by?, max_segments?,
    model_config_id?, feature_cols?}}`. Missing keys per sector fall back to the
    run's own `seg_split_by`/`seg_max_segments`/`model_config_id`/`feature_cols_json`.
- **`calibration_run_logs`** — `run_id`→calibration_runs.run_id, level/message/ts.
- **`calibration_run_segments`** — segments of a calibration run (e.g., by sector &
  subsector). `calibration_run_id`→calibration_runs.id.
  - `model_config_id` — which ModelConfig actually trained
    this segment (nullable; null for segments trained before this column existed).

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

## Auth & RBAC tables (`api/auth/models.py`, `api/roles/models.py`)

### `user_sessions`
- **`sid`** — UUID primary key (session ID, embedded in JWT `jti`).
- **`user_email`** — indexed FK → `users.email`.
- **`issued_at`**, **`expires_at`** — datetimes.
- **`revoked_at`** — NULL while active; set on explicit logout, forced revocation, or
  superseded by a new login (single-session-per-user policy).
- **`ip`**, **`user_agent`** — recorded at issue time for audit.
- Used as the JWT blocklist: `is_revoked(jti)` looks up `sid` and checks `revoked_at`.
  `purge_expired()` cleans up rows past `expires_at`.

### `roles`
- **`name`** — unique string PK (role name, e.g. `"sysadmin"`, `"analyst"`, `"viewer"`).
- **`description`** — human-readable label.
- **`permissions`** — JSON array of permission strings (e.g. `["datasets:read",
  "calibrations:write"]`) or `["*"]` for superuser wildcard.
- **`is_system`** — boolean; `True` for built-in roles (`sysadmin`) which cannot be
  deleted or renamed via the API.
- **`created_by`** — email of the user who created this role (nullable for seeded roles).
- **`created_at`**, **`updated_at`** — timestamps.

> **`users.role`** — stores the role *name* as a plain string column. There is **no
> foreign key** to the `roles` table; referential integrity is enforced in the API layer
> (the endpoint validates that the supplied role name exists in `roles` before saving).
> This avoids cascade complexity when roles are renamed or deleted: the API blocks
> deletion of a role that is still assigned to any user (409 + count).

> **Legacy tables removed:** the old `roles` permission-matrix table and `active_session`
> tracking table were dropped in the auth-RBAC rebuild migration (Alembic migration
> `c3d5f7a9b1e2`). The new `user_sessions` and updated `roles` tables replace them.

## Conventions
- Runs carry an immutable UUID `run_id` (string) plus the integer PK `id`. FKs from
  child run-tables point at `id`; cross-domain references and logs key off `run_id`.
- Every model has a `to_dict()` (or similar) serializer used by routes — keep it in
  sync when adding columns.
