# Financial Forecast — target-variable multi-select

**Date:** 2026-07-07
**Area:** Analysis → Financial Forecast (`services/client/src/views/credit_risk/CreditRiskForecast.vue`)
**TODO item:** "Financial Forecast page: add multi-select dropdown for which target
variables to show (only show target variables of the active job, not some derived
ones like cogs/revenue)"

## Problem

The Financial Forecast page renders a **hardcoded** metric list from
`_FORECAST_METRIC_DEFS` in `services/server/project/api/credit_risk/routes.py`:
Revenue, COGS/Revenue *ratio*, Total Assets, Short-term Debts.

This is:
- **Incomplete** — the active analysis run may link a `long_term_debts` forecast
  slot, which never appears.
- **Wrong altitude** — `cogs_to_revenue` is a *derived ratio*, not a real forecast
  target, yet it sits alongside actual targets with no way to hide it.
- **Not filterable** — the user cannot choose which of their targets to view.

## Goal

Add a **Targets** multi-select to the page header. Its options are the active
analysis run's **real forecast targets only** — the linked forecast slots, each
backed by a calibration `target_col`. Derived metrics (COGS/Revenue ratio) are
excluded from this page. The grid renders only the selected targets.

## Design

### Backend — `services/server/project/api/credit_risk/routes.py`

The active credit-risk run links `ForecastRun`s via `CreditRiskForecastInput`
rows keyed by `slot` (`_slot_forecast_runs(cr)` → `{slot: ForecastRun}`). The real
target slots are: `total_assets`, `short_term_debts`, `long_term_debts`,
`total_revenue`, `total_cogs`.

1. **`GET /analysis/meta`** — add a `forecast_targets` array. One entry per present
   slot that is a real target, in a stable canonical order:

   ```python
   _FORECAST_TARGET_SLOTS = [
       ("total_assets",     "Total Assets"),
       ("short_term_debts", "Short-term Debts"),
       ("long_term_debts",  "Long-term Debts"),
       ("total_revenue",    "Revenue"),
       ("total_cogs",       "COGS"),
   ]
   ```

   Each emitted entry: `{ "key": slot, "title": title }` for `slot in slots`.
   The existing `available_metrics` map stays for backward compatibility.

2. **`GET /analysis/forecast`** — accept an optional `targets` query param
   (comma-separated slot keys). Build the metric list **dynamically** from the
   present target slots (using the same canonical order + titles), filtered to the
   requested keys when provided. Drop the `cogs_to_revenue` derived branch from
   this endpoint. Each metric reuses the existing indexed-history + scenario logic
   (`_historical_series`, `_variable_levels`, `_all_scenarios`, `to_index`).

   - Unknown/absent requested keys are ignored (defensive).
   - No `targets` param → return all present target slots.

### Frontend — `services/client/src/views/credit_risk/CreditRiskForecast.vue`

- Add reactive `forecastTargets` (options from `meta.forecast_targets`) and
  `selectedTargets` (array of slot keys), defaulting to **all** target keys.
- Add a **Targets** `EySelect` (`:multiple`, `showToggleAll`, `filter`) in the
  header `#actions`, alongside Sector and Company. `optionLabel="title"`,
  `optionValue="key"`.
- `fetchForecast()` passes `targets: selectedTargets.value.join(',')` (omit when
  all selected, to keep URLs clean — optional). Re-fetch on `selectedTargets`
  change (watch).
- Empty selection → render a friendly "Select at least one target variable"
  panel instead of the grid; skip the network call.

### API client — `services/client/src/api/creditRiskAPI.js`

`analysisForecast(params)` already forwards `params` verbatim — no change. The
view adds `targets` to its params object.

## Out of scope (YAGNI)

- Sector Heatmap page (keeps its own metric set incl. derived ratios).
- ECL / PD-LGD pages.
- Per-company target availability logic (targets are run-level, not company-level).

## Testing / verification

- Load the page with an active analysis run linking ≥2 target slots → dropdown
  lists exactly those targets (no COGS/Revenue *ratio* entry).
- Deselect one target → its card disappears; reselect → reappears.
- Deselect all → empty-state panel, no request.
- Backend: `/analysis/meta` returns `forecast_targets`; `/analysis/forecast?targets=total_assets`
  returns only that metric.
