# Financial Forecast — Target Multi-Select Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Targets multi-select to the Analysis → Financial Forecast page so users choose which real forecast target variables to chart (excluding derived ratios like COGS/Revenue).

**Architecture:** The active credit-risk run links `ForecastRun`s via `CreditRiskForecastInput` rows keyed by `slot`. We expose those real target slots from `/analysis/meta`, make `/analysis/forecast` build its metric list dynamically from present slots (dropping the derived `cogs_to_revenue` branch) and filter by an optional `targets` param, then add an `EySelect` multi-select in the Vue view.

**Tech Stack:** Flask (`services/server`), Vue 3 `<script setup>` + PrimeVue 3 + custom `EySelect` (`services/client`).

## Global Constraints

- Production-grade, banking app — no throwaway shortcuts; reuse existing abstractions.
- `run_id` (UUID) is immutable; never mutate existing runs.
- PrimeVue stays on v3.
- After any Python edit, from `services/server/`: `ruff check . --exclude migrations --fix && ruff format . --exclude migrations`.
- Never add `Co-Authored-By` trailers. **Only commit when the user explicitly says to** — steps below that say "Commit" are gated on that instruction; otherwise leave changes staged and uncommitted.
- All `/api/*` routes require auth; `@require_perm("credit_risk:read")` already applied on these endpoints.

---

### Task 1: Backend — expose real forecast targets and filter the forecast endpoint

**Files:**
- Modify: `services/server/project/api/credit_risk/routes.py`
  - `_FORECAST_METRIC_DEFS` region (lines ~779-804) — add a canonical target-slot table.
  - `get_analysis_meta` (lines ~1002-1037) — add `forecast_targets`.
  - `get_analysis_forecast` (lines ~1195-1331) — build metrics dynamically, filter by `targets`, drop the derived `cogs_to_revenue` branch.

**Interfaces:**
- Consumes (existing, unchanged): `_get_analysis_run(run_id)`, `_analysis_portfolio_df(cr)`, `_slot_forecast_runs(cr) -> dict[str, ForecastRun]`, `_historical_series(fr, sector, client_id) -> dict[int,float]`, `_variable_levels(rows_df, fr, scen, {}) -> dict[int,float]`, `_all_scenarios(fr) -> list[str]`.
- Produces:
  - Module constant `_FORECAST_TARGET_SLOTS: list[tuple[str, str]]` — canonical `(slot_key, title)` order.
  - `/analysis/meta` response gains `forecast_targets: list[{"key": str, "title": str}]`.
  - `/analysis/forecast` accepts optional `?targets=slot1,slot2`; returns `metrics` list whose `key` values are slot keys from `_FORECAST_TARGET_SLOTS` (no `cogs_to_revenue`).

- [ ] **Step 1: Add the canonical target-slot table**

Immediately above `_FORECAST_METRIC_DEFS` (around line 779), add:

```python
# Real forecast targets that the Financial Forecast page can chart — each maps to
# a linked ForecastRun "slot" (see _slot_forecast_runs). Derived ratios (e.g.
# COGS/Revenue) are intentionally excluded here; they live on the Heatmap page.
# Order is canonical and drives both the dropdown and the card grid.
_FORECAST_TARGET_SLOTS: list[tuple[str, str]] = [
    ("total_assets", "Total Assets"),
    ("short_term_debts", "Short-term Debts"),
    ("long_term_debts", "Long-term Debts"),
    ("total_revenue", "Revenue"),
    ("total_cogs", "COGS"),
]
```

- [ ] **Step 2: Add `forecast_targets` to `/analysis/meta`**

In `get_analysis_meta`, extend the returned JSON. Replace the final `return jsonify({...})` block (lines ~1021-1037) with:

```python
    return jsonify(
        {
            "run_id": cr.run_id,
            "sectors": sorted(companies_by_sector.keys()),
            "companies_by_sector": companies_by_sector,
            "forecast_targets": [
                {"key": key, "title": title}
                for key, title in _FORECAST_TARGET_SLOTS
                if key in slots
            ],
            "available_metrics": {
                k: k in slots
                for k in (
                    "total_assets",
                    "short_term_debts",
                    "long_term_debts",
                    "total_revenue",
                    "total_cogs",
                )
            },
        }
    ), 200
```

- [ ] **Step 3: Make `/analysis/forecast` dynamic + filterable**

In `get_analysis_forecast`, after `client_id = request.args.get("client_id") or None` (line ~1199), add parsing of the `targets` param:

```python
    requested = request.args.get("targets")
    requested_keys = (
        {t.strip() for t in requested.split(",") if t.strip()} if requested else None
    )
```

Then replace the entire metric-building loop — from `metrics_out = []` (line ~1222) through the end of the `for spec in _FORECAST_METRIC_DEFS:` loop (line ~1327, just before the final `return jsonify(...)`) — with the dynamic version below. Note: the `series_points` helper defined at line ~1219 is still used, keep it.

```python
    metrics_out = []
    for slot_key, title in _FORECAST_TARGET_SLOTS:
        fr = slots.get(slot_key)
        if not fr:
            continue
        if requested_keys is not None and slot_key not in requested_keys:
            continue

        hist = _historical_series(fr, sector, client_id)
        base_year = min(hist) if hist else None
        base_val = hist.get(base_year) if base_year is not None else None

        def to_index(levels: dict, base_val=base_val) -> list[dict]:
            if not base_val:
                return series_points(levels)
            return [
                {"year": y, "value": round(levels[y] / base_val * 100, 2)}
                for y in sorted(levels)
            ]

        history_points = to_index(hist)
        scenarios_out = {}
        for scen in _all_scenarios(fr):
            levels = _variable_levels(rows_df, fr, scen, {})
            scenarios_out[scen] = to_index(levels)

        baseline_pts = scenarios_out.get("Baseline", [])
        metrics_out.append(
            {
                "key": slot_key,
                "title": title,
                "unit": f"Indexed · {base_year} = 100" if base_year else "Indexed",
                "available": True,
                "history": history_points,
                "scenarios": scenarios_out,
                "value": baseline_pts[-1]["value"] if baseline_pts else None,
                "delta_pct": (
                    round(
                        (baseline_pts[-1]["value"] - history_points[-1]["value"])
                        / history_points[-1]["value"]
                        * 100,
                        1,
                    )
                    if baseline_pts and history_points and history_points[-1]["value"]
                    else None
                ),
                "base_year": base_year,
            }
        )
```

Note: `_FORECAST_METRIC_DEFS` is now unused by this endpoint. Check for other references before deleting it — Step 4.

- [ ] **Step 4: Check whether `_FORECAST_METRIC_DEFS` is still referenced**

Run: `cd services/server && grep -rn "_FORECAST_METRIC_DEFS" project/`
Expected: only the definition remains. If so, delete the `_FORECAST_METRIC_DEFS = [...]` block (lines ~779-804). If other references exist, leave it in place.

- [ ] **Step 5: Format**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`
Expected: no errors; files reformatted.

- [ ] **Step 6: Manual endpoint smoke test**

With the dev server + an active analysis run linking ≥2 target slots:
Run: `curl -s -b cookies.txt "http://localhost:5001/api/credit-risk/analysis/meta" | python -m json.tool`
Expected: response includes `"forecast_targets": [ {"key": "total_assets", "title": "Total Assets"}, ... ]` — no `cogs_to_revenue` entry.
Run: `curl -s -b cookies.txt "http://localhost:5001/api/credit-risk/analysis/forecast?sector=<S>&targets=total_assets" | python -m json.tool`
Expected: `metrics` contains exactly one entry with `"key": "total_assets"`.

(If no live server/session is available, verify by reading the diff: `forecast_targets` built from `_FORECAST_TARGET_SLOTS ∩ slots`; loop filters on `requested_keys`; no `cogs_to_revenue` branch remains.)

- [ ] **Step 7: Commit (only if the user has said to commit)**

```bash
git add services/server/project/api/credit_risk/routes.py
git commit -m "feat(credit-risk): expose real forecast targets and filter analysis/forecast by targets"
```

---

### Task 2: Frontend — Targets multi-select on the Financial Forecast page

**Files:**
- Modify: `services/client/src/views/credit_risk/CreditRiskForecast.vue`

**Interfaces:**
- Consumes: `creditRiskAPI.analysisMeta()` → `data.forecast_targets: [{key, title}]`; `creditRiskAPI.analysisForecast({ sector, client_id, targets })` (params forwarded verbatim by the existing client — no client change needed).
- Produces: none (leaf view).

- [ ] **Step 1: Add reactive target state**

In `<script setup>`, after the `selectedCompany` ref (line ~17), add:

```js
const forecastTargets = ref([])          // [{ key, title }] from meta
const selectedTargets = ref([])          // array of slot keys
```

- [ ] **Step 2: Populate targets + default-all in `fetchMeta`**

In `fetchMeta`, inside the `try` after `companiesBySector.value = data.companies_by_sector ?? {}` (line ~28), add:

```js
    forecastTargets.value = data.forecast_targets ?? []
    selectedTargets.value = forecastTargets.value.map((t) => t.key)
```

- [ ] **Step 3: Pass `targets` to the forecast request**

In `fetchForecast`, replace the `analysisForecast` call (lines ~44-47) with:

```js
    const { data } = await creditRiskAPI.analysisForecast({
      sector: selectedSector.value,
      client_id: selectedCompany.value || undefined,
      targets: selectedTargets.value.length
        ? selectedTargets.value.join(',')
        : undefined,
    })
```

- [ ] **Step 4: Guard empty selection + re-fetch on change**

At the top of `fetchForecast`, replace the existing guard `if (!selectedSector.value) return` (line ~40) with:

```js
  if (!selectedSector.value) return
  if (!selectedTargets.value.length) { forecastData.value = { metrics: [] }; return }
```

Add a watcher next to the existing ones (after line ~58):

```js
watch(selectedTargets, fetchForecast)
```

- [ ] **Step 5: Add the Targets multi-select to the header**

In the template `#actions` slot, after the Company `field-col` block (closing `</div>` at line ~164), add a new field column:

```html
        <div class="field-col">
          <span class="field-label">Targets</span>
          <EySelect
            v-model="selectedTargets"
            :options="forecastTargets"
            optionLabel="title"
            optionValue="key"
            multiple
            showToggleAll
            filter
            :disabled="!forecastTargets.length"
            style="width: 14rem"
          />
        </div>
```

- [ ] **Step 6: Empty-selection state in template**

In the template, immediately before the `<div class="fin-grid">` (line ~191), add an empty-state branch and wrap the grid:

```html
        <div
          v-if="!selectedTargets.length"
          class="panel flex flex-column align-items-center justify-content-center gap-2"
          style="height: 16rem"
        >
          <i class="pi pi-filter-slash text-3xl text-color-secondary opacity-50" />
          <div class="text-sm font-medium">Select at least one target variable</div>
        </div>
        <div v-else class="fin-grid">
```

(The existing `<div class="fin-grid">` opening tag is replaced by the `<div v-else class="fin-grid">` above; its closing `</div>` stays.)

- [ ] **Step 7: Verify in the browser (webapp-testing skill)**

Start the frontend (`npm run dev` in `services/client`) with an active analysis run. Confirm:
- Targets dropdown lists exactly the active run's real targets — no "COGS / Revenue" ratio entry.
- Deselecting a target removes its card; reselecting restores it.
- Deselecting all shows the "Select at least one target variable" panel and fires no request (check Network tab).

- [ ] **Step 8: Commit (only if the user has said to commit)**

```bash
git add services/client/src/views/credit_risk/CreditRiskForecast.vue
git commit -m "feat(analysis): add target-variable multi-select to Financial Forecast page"
```

---

## Self-Review

- **Spec coverage:** Backend `forecast_targets` (Task 1 Step 2) ✓; dynamic + `targets` filter, drop derived ratio (Task 1 Step 3) ✓; multi-select default-all (Task 2 Steps 1-2, 5) ✓; empty state (Task 2 Steps 4, 6) ✓; API client unchanged (confirmed — `analysisForecast` forwards params) ✓; out-of-scope pages untouched ✓.
- **Placeholder scan:** none — all steps carry concrete code/commands.
- **Type consistency:** `forecast_targets` entries `{key, title}` produced in Task 1 Step 2 are consumed with `optionLabel="title" optionValue="key"` in Task 2 Step 5 ✓. Metric `key` = slot key in both endpoint (Task 1 Step 3) and existing card rendering (`fin.key`, `fin.title`) ✓. Note the removed `cogs_to_revenue` special-case in the template (`fin.key === 'cogs_to_revenue'`, lines ~201, ~206) is now dead but harmless — it simply never matches; left untouched to keep the diff minimal.
