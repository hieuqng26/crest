# Real 1-Year Rating Transition Matrix — Design

**Date:** 2026-07-08
**Area:** Credit Risk → Transitions (`/credit-risk/transitions`)
**Status:** Approved for planning

## Problem

`services/client/src/views/credit_risk/CreditRiskTransitions.vue` renders a
hardcoded 8×8 demo transition matrix (`const matrix`, lines ~6–15) with an
invented AAA…D axis. This is a routed production view showing fabricated numbers,
violating the project rule "Don't fabricate data" (`.claude/docs/design.md`).

## What real data is available

Every successful `CreditRiskRun` stores, per client, a `CreditRiskResult` row
whose `kmv_json` is a list of `{YEAR, SCENARIO, Rating, PD, LGD, …}` records. The
KMV model (`core/credit_risk/kmv.py:206-208`) assigns each client a **Rating per
year per scenario** by snapping its cumulative PD to the nearest notch on the
`pd_ratings` curve.

A genuine 1-year transition matrix is therefore computable: count
`Rating[year_t] → Rating[year_t+1]` transitions across all clients for a chosen
scenario, then row-normalise to probabilities.

### Two realities this surfaces

1. **The rating scale is 19 Moody's notches (Aaa1 … Caa3)**, seeded in migration
   `i4j6k8l0m2n4_add_pd_ratings.py` — **not** the hardcoded 8 letter grades, and
   there is **no "D"/default absorbing state**. The current axis labels are as
   fictional as the numbers.
2. **This is a *forecast-implied* transition matrix** — derived from KMV rating
   paths across the forecast horizon — **not** a historical cohort/agency matrix
   from observed rating histories. The platform has no rating-history table. This
   is an honest, defensible construction, but the UI must label it as such so an
   analyst never mistakes it for an agency-style historical matrix.

## Decisions (confirmed with user)

- **Rating axis: observed notches only.** The matrix spans exactly the notches
  present in the active run's results, ordered by `pd_ratings.category`
  (best→worst). No invented notch→letter mapping. Axis size is dynamic
  (typically 6–10 notches).
- **Scenario: toggle, default Baseline.** A chip row (same pattern as the
  Heatmap page) lets the analyst switch scenario; the matrix recomputes per
  scenario. Available scenarios come from the response.

## Architecture

Three isolated units, presentation-only frontend:

### 1. Pure computation helper (backend)

`_rating_transitions(results, pd_rating_df, scenario) -> dict` in
`project/api/credit_risk/routes.py` (private helper section).

- **Input:** list of `CreditRiskResult` rows (or their parsed `kmv_json`),
  the curve's `pd_rating_df` (for category ordering), and a scenario string.
- **Logic:**
  - For each result, parse `kmv_json`, filter to rows where
    `SCENARIO == scenario` (case-insensitive, matching the existing
    `str(k.get("SCENARIO","")).lower()` convention in `_run_results_df`).
  - Sort by `YEAR`; for each consecutive year pair, tally
    `(from_rating, to_rating)` into a counter. Skip a client with fewer than 2
    rows for that scenario.
  - `observed = ` union of all from/to ratings seen.
  - Order `observed` by the rating's `category` in `pd_rating_df`
    (best→worst). Any rating not present in `pd_rating_df` (shouldn't happen —
    KMV picks ratings from that same frame) sorts last, deterministically.
  - Build, for each from-rating row: `counts[to]` per observed to-rating and
    `row_total = sum(counts)`; `matrix[i][j] = round(counts/row_total*100, 1)`
    (row_total is always ≥1 for any from-rating that appears).
- **Output:** dict with `ratings`, `matrix`, `counts`, `row_totals`,
  `n_transitions`, `n_clients`, `years` (min/max year observed).
- **Testable without Flask** — takes plain data in, returns a plain dict.

### 2. Endpoint (thin wrapper)

`GET /credit-risk/analysis/transitions?run_id=<optional>&scenario=Baseline`,
`@require_perm("credit_risk:read")`.

- Resolve run via existing `_get_analysis_run(run_id)` — active run when omitted;
  raises `ValueError` → **404** for no-active-run / not-successful (same contract
  the Heatmap relies on).
- Load `CreditRiskResult` rows for the run (indexed by `run_id`).
- Determine available scenarios = distinct `SCENARIO` values across all
  `kmv_json` (ordered Baseline / Adverse / Severely Adverse, then alpha — reuse
  the ordering dict already used by `_all_scenarios`).
- Default `scenario` to `Baseline` if present, else the first available. If the
  caller requests a scenario not present → **422** with a clear message.
- Build (or read from cache) a `{scenario: _rating_transitions(...)}` map over all
  available scenarios in one pass, cache it under `cr_transitions:{run_id}`, and
  serve the requested scenario. If the chosen scenario yields no transitions →
  **422** "No transition data for the active analysis run." (Defensive: KMV
  requires ≥2 distinct years, so a successful run always yields transitions.)

**Response shape:**
```json
{
  "run_id": "…",
  "scenario": "Baseline",
  "scenarios": ["Baseline", "Adverse", "Severely Adverse"],
  "ratings": ["Baa1", "Baa2", "Baa3", "Ba1", "Ba2"],
  "matrix":     [[88.0, 9.1, 2.1, 0.5, 0.3], …],
  "counts":     [[123, 12, 3, 1, 0], …],
  "row_totals": [139, …],
  "n_transitions": 1234,
  "n_clients": 250,
  "years": [2024, 2029]
}
```

`counts` / `row_totals` let the UI surface sample size on hover — in banking a
100% cell backed by 1 observation must be distinguishable from a well-populated
one.

**Caching:** mirror `_run_results_df` — memoise in the app `cache` under a
**single per-run key `cr_transitions:{run_id}`** holding every scenario's matrix
(a successful run's results are immutable except via segment recompute). The
endpoint computes all scenarios in one pass, caches the whole structure, and
serves the requested scenario from it. Invalidation is then a single
`cache.delete(f"cr_transitions:{run_id}")` added next to the existing
`cr_run_results:{run_id}` delete at `workers/tasks.py:2094`. TTL 3600, matching
`_run_results_df`.

### 3. API client

Add to `services/client/src/api/creditRiskAPI.js`:
```js
analysisTransitions: (params) =>
  httpClient.get('/credit-risk/analysis/transitions', { params }),
```

### 4. Frontend view rewrite

Rewrite `CreditRiskTransitions.vue` `<script setup>` to fetch instead of
hardcode, **keeping the exact ink-diagonal / monochrome-ramp rendering and grid
markup**.

- **Scenario chip row** (same markup/CSS as Heatmap's metric chips), driven by
  `scenarios`, default Baseline; switching refetches.
- **Dynamic axis** from `ratings`; grid columns via
  `v-bind('ratings.length')` exactly as Heatmap does with `years.length`.
- **`cellStyle` preserved:** diagonal = `var(--ink)` bg / `var(--yellow)` text;
  off-diagonal = gray-intensity ramp. Because real rows are normalised to 100%
  (unlike the demo's `val/30` scaling), scale the alpha ramp against the **row
  max** so off-diagonal contrast stays meaningful whether migration is
  concentrated or diffuse.
- **Cell hover** shows `count / row_total` (sample size) via a `title` attr.
- **Empty / error states mirror Heatmap:**
  - **404** → "No active analysis run" panel + Job History button.
  - **422 / other** → message panel showing `error`.
  - Loading spinner while fetching.
- **Honest subtitle:** label the matrix as *forecast-implied from KMV rating
  paths* (not a historical agency matrix).

### 5. No migration

Pure read over existing `credit_risk_results.kmv_json` + `pd_ratings`. No schema
change.

## Testing

- **Unit (backend):** `_rating_transitions` with synthetic result rows —
  - basic multi-client transitions row-normalise to 100 and order by category;
  - a client with a single year for the scenario is skipped;
  - ratings absent from the run don't appear on the axis;
  - `counts` / `row_totals` / `n_transitions` are correct.
- **Endpoint:** 404 when no active run; 422 for an unknown scenario; 200 with the
  documented shape for a seeded successful run; scenario default falls back when
  Baseline absent.
- **Frontend:** manual verification via the preview workflow — active run shows a
  real matrix with the observed-notch axis and working scenario toggle; no active
  run shows the empty state.

## Out of scope

- Historical/agency cohort transition matrices (no rating-history data exists).
- Collapsing notches into letter grades (explicitly rejected — would invent a
  mapping not in the codebase).
- Any change to KMV/ECL math or the `pd_ratings` seed.
