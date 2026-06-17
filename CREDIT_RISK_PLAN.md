# Credit Risk Implementation Plan

> Wiring up the existing `kmv.py` and `ecl.py` engines into an end-to-end Credit Risk flow:
> data ingestion → KMV → ECL → frontend dashboards.

---

## 1. Issues with the current code

### `services/server/project/core/credit_risk/kmv.py`

1. **Module-level CSV read.**
   `pd_rating = pd.read_csv('services/server/project/data/db/PD_Calibrate_CP.csv')` runs at import time, using a working-directory-relative path. Crashes the Celery worker, the Flask app factory, and migrations if cwd ≠ repo root. **Move PD rating into the DB** and query at call-time.
2. **Forecast schema is hard-coded.** Columns `SCENARIO`, `Total_Asset`, `CL`, `NonCL`, `YEAR` (mixed case) are required. Calibration forecasts produce different column names, so we'll need an adapter layer or a documented contract.
3. **`equity_finance=0.` is undocumented.** Silently scales liability deltas. Rename to `equity_financing_ratio` and document.
4. **`generate_kmv` mutates derived NumPy arrays.** Low-grade — should `.copy()` per scenario slice.
5. **`Tenor[-2]` assumes ≥ 2 forecast years.** Add an explicit guard with a clear error.
6. **No cross-scenario year-range assertion.** If scenarios differ in year coverage, the downstream merge with ECL silently misaligns.

### `services/server/project/core/credit_risk/ecl.py`

1. **`ECL_LIFETIME_LENGTH = 5` is a magic constant.** IFRS 9 lifetime varies by instrument — make it a parameter.
2. **Tail rows are dropped silently** (`df = df[df.YEAR <= max_year - ECL_LIFETIME_LENGTH]`). Return the full DF and let the caller slice.
3. **Single `exposure` value per call.** Fine for one client; we'll wrap per-client iteration at the API layer.
4. **Recomputes per-year slices in a Python loop.** Correct but O(n²) on long forecasts. Acceptable for ≤ ~30 years; leave as-is.

### Cross-cutting

1. **Forecast column-name mismatch.** Three numeric forecasts (`total_assets`, `total_shortterm_debts`, `total_longterm_debts`) come from *separate* calibration runs. Each run stores `actual` + `predicted` + `meta` per validation row — no `SCENARIO` concept, no `YEAR` unless `meta` carries it.
   **Solution:** the KMV API accepts either an explicit forecast DF *or* three `run_id`s + a scenario label, and assembles the DF in the format `generate_kmv` expects. Mock data sidesteps this for now.
2. **Per-client iteration.** KMV runs per client; each has its own `E0`, `volE`, `rating`, `r` and its own 3 forecast series. Scope the v1 API to one client per request. Portfolio aggregation is a follow-up.
3. **The pre-existing `/credit-risk/ecl` and `/credit-risk/pd-lgd` endpoints are dummies** that don't use the real engines. Keep them as simple portfolio summaries (mark v1 in a comment); add new endpoints alongside.
4. **Where does credit data live?** Two options:
   - **Reuse `datasets`** with a `kind` column (`calibration` vs `credit`) — lightest touch.
   - New `credit_data` table — cleaner but more code.
   **Chosen:** reuse `datasets` + `kind` column.
5. **`pd_ratings` table.** Only 19 rows. Single table, seeded from the existing CSV in a migration. Later support multiple curves (Moody's, S&P) via a `curve_name` column.

---

## 2. Plan

### Backend

#### 2.1 — New table `pd_ratings`

- New ORM model `PdRating` in `services/server/project/db_models/credit_models.py`.
- Columns: `id`, `curve_name` (default `'moodys'`), `category` (int), `rating` (string), `pd` (float).
- Alembic migration `i4j6k8l0m2n4_add_pd_ratings.py` creates the table and seeds 19 rows from `PD_Calibrate_CP.csv`.

#### 2.2 — Add `datasets.kind` column

- Migration adds `kind VARCHAR(16) NOT NULL DEFAULT 'calibration'` to `datasets`.
- Frontend Credit Risk pages list `datasets WHERE kind='credit'`.
- Existing calibration flow unaffected (default value).

#### 2.3 — Refactor `kmv.py`

- Drop module-level CSV read.
- Rename `generate_kmv → run_kmv(com_info, forecast, pd_rating_df, equity_financing_ratio=0.0)`.
- Add guards: `if len(years) < 2`, `if rating not in pd_rating_df['Rating'].values`, `if any scenario lacks expected cols`.
- `.copy()` per-scenario slices.
- Make helpers private: `_kmv_calibrate`, `_kmv_step`.

#### 2.4 — Refactor `ecl.py`

- Signature: `compute_ecl(forecast_pd_lgd, exposure, discount_rate, lifetime_horizon=5, drop_tail=False)`.
- Return full DF; caller decides what to slice.

#### 2.5 — New helper `mock_credit.py`

- `mock_credit_data(n_clients=50, seed=42)` → DataFrame `[date, client_id, market_cap, vol_equity, rating, risk_free_rate]`.
- `mock_kmv_forecast(client_id, base_year=2024, n_years=10, scenarios=['Baseline','Upside','Downside'], seed=42)` → DataFrame `[YEAR, SCENARIO, Total_Asset, CL, NonCL]`.
- Both reproducible (fixed seed per client).

#### 2.6 — New API endpoints

Replace the dummies, keep them addressable as v1.

| Method | Path | Body / Query | Purpose |
|---|---|---|---|
| `GET`  | `/credit-risk/pd-ratings`            | `?curve=moodys` | Return all rating rows for a curve |
| `GET`  | `/credit-risk/clients`               | `?dataset_id=X` or `?mock=true` | Distinct `client_id`s in a credit dataset |
| `POST` | `/credit-risk/kmv`                   | `{client_id, dataset_id? OR mock=true, scenarios?}` | Run KMV for one client, return per-scenario × per-year DF |
| `POST` | `/credit-risk/ecl`                   | `{kmv_result OR (client_id+mock=true), exposure, discount_rate, lifetime_horizon}` | Compute ECL series |
| `GET`  | `/credit-risk/ecl` *(v1, existing)*  | — | Simplified portfolio summary, retained |
| `GET`  | `/credit-risk/pd-lgd` *(v1, existing)* | — | Simplified PD/LGD summary, retained |

#### 2.7 — Wire it up

- Register `PdRating` import in `project/__init__.py` so `flask db migrate` picks it up.
- Credit Risk blueprint is already registered at `/api/credit-risk`.

### Frontend

#### 2.8 — New API wrapper

- `services/client/src/api/creditRiskAPI.js` mirroring `calibrationsAPI.js`:
  `pdRatings()`, `clients(datasetId)`, `kmv(payload)`, `ecl(payload)`.

#### 2.9 — Update Credit Risk views to use real API + mock data

- **`CreditRiskECL.vue`** and **`CreditRiskPdLgd.vue`**:
  - Add a top-of-page Client Selector (PrimeVue Dropdown) + scenario filter.
  - Replace hard-coded tables/charts with data from the new endpoints.
  - Chart options stay identical — only the data binding changes.
  - Both pages run against `mock=true` initially; flip to real data once calibrations are wired.

#### 2.10 — New Credit Data ingestion page

- `services/client/src/views/credit_risk/CreditRiskData.vue` lists `datasets WHERE kind='credit'`, with the same upload UI as `views/ingest/Datasets.vue`. Reuses the existing dataset upload endpoint with `kind=credit`.
- Add menu entry under "Credit Risk" → "Credit Data".

---

## 3. Out of scope (deferred)

- **Calibration-driven forecast assembly.** Document the contract now; once a calibration result is selected by the user, the API will produce the forecast DF from three runs (`total_assets`, `total_shortterm_debts`, `total_longterm_debts`). Mocked for now.
- **Portfolio aggregation.** Per-client only in v1. A future `/credit-risk/portfolio` endpoint can sum.
- **RBAC for credit endpoints.** Defer until shape is settled.
- **Multiple PD curves** (S&P alongside Moody's). Schema supports it; UI selector deferred.

---

## 4. Verification path

1. `flask db upgrade` → both migrations apply; `pd_ratings` has 19 seeded rows; `datasets.kind` exists.
2. Python shell:
   ```python
   from project.core.credit_risk.mock_credit import mock_kmv_forecast
   from project.core.credit_risk.kmv import run_kmv
   # Should return a DataFrame with PD, LGD, DTD, Rating columns
   ```
3. `POST /credit-risk/kmv` with `{mock: true, client_id: "C0001"}` → rows for 3 scenarios × N years with all KMV columns.
4. `POST /credit-risk/ecl` with the KMV result + exposure → ECL series.
5. Open `/credit-risk/ecl` in browser → chart + table render from API data; switching clients re-fetches.

---

## 5. Files touched

| File | Action |
|---|---|
| `services/server/project/db_models/credit_models.py` | **NEW** — `PdRating` ORM |
| `services/server/migrations/versions/i4j6k8l0m2n4_add_pd_ratings.py` | **NEW** — create + seed `pd_ratings` |
| `services/server/migrations/versions/j5k7l9m1n3o5_add_datasets_kind.py` | **NEW** — add `datasets.kind` |
| `services/server/project/core/credit_risk/kmv.py` | Refactored — drop CSV read, rename, add guards |
| `services/server/project/core/credit_risk/ecl.py` | Refactored — parameterise lifetime, no tail drop |
| `services/server/project/core/credit_risk/mock_credit.py` | **NEW** — `mock_credit_data`, `mock_kmv_forecast` |
| `services/server/project/api/credit_risk/routes.py` | Add 4 new endpoints; keep v1 dummies |
| `services/server/project/__init__.py` | Import `PdRating` |
| `services/client/src/api/creditRiskAPI.js` | **NEW** — API wrapper |
| `services/client/src/views/credit_risk/CreditRiskECL.vue` | Swap mock for API |
| `services/client/src/views/credit_risk/CreditRiskPdLgd.vue` | Swap mock for API |
| `services/client/src/views/credit_risk/CreditRiskData.vue` | **NEW** — credit dataset ingestion |
| `services/client/src/layout/AppMenu.vue` | Add "Credit Data" menu entry |

**Total:** 7 new files, 6 modified.
