# Plan: Speed up slow pages (Heatmap, Financial Forecast, Job History, Job View)

## Context
Four pages load slowly: **Sector Heatmap**, **Financial Forecast**, **Job History**,
and the individual **Job / Workflow view**. Profiling the backend (two Explore passes)
found the cause is almost entirely **N+1 database queries** and a few **unpaginated
list endpoints**, compounded by short polling intervals that re-fire those expensive
endpoints every 3–5 s. CLAUDE.md explicitly forbids N+1 queries and mandates
pagination — this brings the hot paths in line.

The fixes are surgical: batch the per-row `.query.get()` fan-outs into single
`IN (...)` lookups, add pagination where it's missing, and cache/short-circuit the
few remaining hot spots. No behavioural or schema changes; response shapes are
preserved (a paginated `{items, total, page, pages}` envelope is added to two list
endpoints and their sole caller is updated to match).

---

## Root causes (measured)

**Job History** hits 4 endpoints per load *and per 5 s poll*; three do N+1:
- `forecast_runs list_runs` (`forecast_runs/routes.py:26`) — **no pagination**, and
  `ForecastRun.to_dict()` (`forecast_models.py:44,45,51`) fires **3 queries per row**
  → `1 + 3N`.
- `credit_risk list_runs` (`credit_risk/routes.py:221`) — **no pagination**;
  `Dataset.query.get` per row + lazy `forecast_inputs_rel` in `to_dict()` → `1 + 2N`.
- `calibrations list_runs` (`calibrations/routes.py:33`) — paginated (good) but lazy
  `model_config`/`dataset` per row → `1 + 2N` (N≤200).

**Job View — Workflow detail** `get_workflow` (`workflows/routes.py:183`):
`≈ 4 + 4T` queries (T targets). `fr.to_dict()` re-fetches the *same* CalibrationRun +
ModelConfig already loaded in the loop (3 redundant queries/target), plus a 4× dataset
`.get` loop (212-219). Re-fired every **3 s** by `WorkflowDetail.vue:39`.

**Job View — individual** `credit_risk get_run` (`credit_risk/routes.py:578`) loads
**every** `CreditRiskResult` row just to derive distinct `client_ids` (line 587-588) —
repeated every 3 s.

**Heatmap / Financial Forecast** (`credit_risk/routes.py:1030` / `:1185`): the only
DB cost that scales with the inner loops is `CalibrationRun.query.get(fr.calibration_run_id)`
inside `_historical_series` (`:890`) — fires **S×M** (heatmap overview), **C_sec×M**
(heatmap drill-down, a true per-client N+1), or **T** (forecast) times, even though the
frame it guards is already `g`-cached. The heatmap drill-down also does an O(C_sec²)
boolean re-scan (`:1132-1134`).

---

## Changes

### 1. `ForecastRun.to_dict()` — kill the 3-query fan-out (`db_models/forecast_models.py:37`)
This single method is the biggest multiplier (Job History forecast list, workflow
detail, individual forecast view). Add an optional pre-resolved context so callers that
already hold the objects don't re-query, and keep the self-contained path for single
callers:
- Signature → `to_dict(self, *, cal_run=None, dataset=None, config_name=None)`.
- Use the passed values when present; otherwise fall back to the current
  `.query.get()` lookups (so existing single-item callers are unchanged).

### 2. `forecast_runs list_runs` — paginate + batch (`forecast_runs/routes.py:26`)
- Add `page`/`per_page` (default 50) mirroring `calibrations list_runs`, returning the
  same `{items, total, page, pages}` envelope.
- Batch-load the referenced `CalibrationRun`, `Dataset`, `ModelConfig` via
  `.filter(id.in_(...))` dict lookups, then call `r.to_dict(cal_run=…, dataset=…,
  config_name=…)`.

### 3. `credit_risk list_runs` — paginate + batch datasets (`credit_risk/routes.py:221`)
- Add pagination with the same `{items, total, page, pages}` envelope; batch `Dataset`
  via `id.in_(...)`.
- Eager-load `forecast_inputs_rel` with `selectinload` for the page to kill the lazy
  per-row load inside `to_dict()`.

### 3b. Frontend: consume the paginated envelope (`jobs.js`, `creditRiskAPI.js`)
Both endpoints are called **only** from `jobs.js` `listJobs()` (`forecastRunsAPI.list()`
+ `creditRiskAPI.listRuns()`), which currently expects `.data` to be an array.
- `listJobs()` passes `{ per_page: 200 }` to each (same as the existing workflows call)
  and reads `.data.items` instead of `.data` for those two.
- `creditRiskAPI.listRuns` gains an optional `params` arg: `listRuns: (params) =>
  httpClient.get('/credit-risk/runs', { params })`.
- `forecastRunsAPI.list` already forwards `params` — no change there.
- Confirmed no other caller uses the array shape (grep verified: only `jobs.js`).

### 4. `calibrations list_runs` — eager-load relationships (`calibrations/routes.py:40`)
Replace the plain `.join()` (which does not populate relationship attrs) with
`selectinload(CalibrationRun.model_config)` + `selectinload(CalibrationRun.dataset)` so
the per-row `.model_config`/`.dataset` accesses (53-57) don't each fire a query. Keeps
the join only where needed for ordering/filtering.

### 5. `get_workflow` — remove redundant per-target queries (`workflows/routes.py:183`)
- `cals` already loaded; build `cal_by_id`. Pass each cal into `fr.to_dict(cal_run=cal,
  dataset=<batched>, config_name=<from cal.model_config>)` so the 3T redundant queries
  become 0.
- Batch the 4 dataset-name lookups (212-219) into one `id.in_(...)` query.
- Eager-load `model_config` for `cals` (one `selectinload`) so `cal.model_config` in the
  loop is free.
- Net: `≈ 4 + 4T` → `≈ 6` queries.

### 6. `credit_risk get_run` — don't scan all results for client_ids (`credit_risk/routes.py:578`)
Replace `CreditRiskResult.query.filter_by(...).all()` + set-comprehension with a single
distinct query:
`db.session.query(CreditRiskResult.client_id).filter_by(run_id=...).distinct().all()`.
Loads only the distinct ids, not every row. (Same pattern at `get_active_run:319` — apply
there too.)

### 7. Heatmap / Forecast — stop re-`get`-ing CalibrationRun (`credit_risk/routes.py:890`)
`_historical_series` calls `CalibrationRun.query.get(fr.calibration_run_id)` on every
invocation. Cache the resolved `cal_run` (or just its `id`+`target_col`+`dataset_id`)
on `g` keyed by `fr.id`, alongside the existing `_hist_frame_` cache. Removes S×M /
C_sec×M / T redundant identical queries per request.
- Heatmap drill-down O(C_sec²) rescan (`:1132-1134`): pre-group `sector_rows` by
  `client_id` once (`groupby`) instead of re-filtering per client.

### 8. Polling cadence (frontend)
Backoff the timers that re-fire the detail endpoints:
- `WorkflowDetail.vue:39` and `JobDetail.vue:37`: **3 s → 5 s**.
- `JobHistory.vue:51`: keep **5 s** (already gated on `hasActive`).

---

## Critical files
- `services/server/project/db_models/forecast_models.py` (to_dict signature)
- `services/server/project/api/forecast_runs/routes.py` (list_runs)
- `services/server/project/api/credit_risk/routes.py` (list_runs, get_run,
  get_active_run, `_historical_series`, heatmap drill-down)
- `services/server/project/api/calibrations/routes.py` (list_runs eager-load)
- `services/server/project/api/workflows/routes.py` (get_workflow)
- Frontend: `services/client/src/api/creditRiskAPI.js`, `services/client/src/api/jobs.js`,
  `services/client/src/views/jobs/WorkflowDetail.vue`, `JobDetail.vue`.

Reuse existing patterns: `selectinload` (SQLAlchemy), the `{items,total,page,pages}`
envelope from `calibrations list_runs`, the `g`-cache idiom already in
`_historical_series`/`_cached_variable_index`.

---

## Verification
1. Backend lint: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`.
2. Query-count check: enable SQLAlchemy echo (or a per-request query counter) and hit:
   - `GET /api/forecast-runs?page=1` → expect `~4` queries regardless of N (was `1+3N`).
   - `GET /api/credit-risk/runs?page=1` → constant queries (was `1+2N`).
   - `GET /api/calibrations/` → `~3` (was `1+2N`).
   - `GET /api/workflows/<run_id>` → `~6` (was `4+4T`).
   - `GET /api/credit-risk/runs/<id>` → no full-result scan.
3. Heatmap/Forecast: load Financial Forecast + Sector Heatmap (overview and a
   drilled sector); confirm identical JSON to before and a visibly faster response.
4. Frontend: `cd services/client && npm run build`; smoke-test Job History, Workflow
   view, Financial Forecast, Heatmap in the browser — same data, faster loads, polling
   still refreshes live jobs.
5. Diff the JSON responses pre/post change for one run of each endpoint to prove the
   response shape is byte-identical (except the new pagination envelope on the two
   list endpoints).
