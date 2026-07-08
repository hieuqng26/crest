# Real 1-Year Rating Transition Matrix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded 8×8 demo transition matrix in the routed
`/credit-risk/transitions` view with a real, forecast-implied 1-year rating
transition matrix computed from the active analysis run's KMV rating paths.

**Architecture:** A pure core module computes per-scenario transition matrices
from parsed KMV rows (no Flask, unit-testable by file-path import like the
existing `test_credit_risk.py`). A thin Flask endpoint in the `credit_risk`
blueprint resolves the active run, feeds `CreditRiskResult.kmv_json` to that
module, caches the result per run, and serves the requested scenario. The Vue
view becomes presentation-only: fetch, scenario toggle, dynamic observed-notch
axis, empty states — keeping the existing ink-diagonal / monochrome-ramp
rendering.

**Tech Stack:** Python/Flask, Flask-JWT-Extended, Flask-Caching, pandas
(existing helpers), pytest; Vue 3 `<script setup>`, PrimeVue 3, axios.

## Global Constraints

- **PrimeVue stays on v3.** Do not use v4 APIs.
- **Don't fabricate data.** The matrix must derive entirely from real
  `CreditRiskResult.kmv_json` + `pd_ratings`; no demo numbers, no invented axis.
- **Rating axis = observed Moody's notches only** (Aaa1…Caa3 subset present in
  the run), ordered by `pd_ratings.category` best→worst. No notch→letter
  bucketing.
- **Honest labelling:** the UI must present this as *forecast-implied from KMV
  rating paths*, not a historical/agency cohort matrix.
- **Production-grade:** single indexed query per run, cached (TTL 3600) with
  invalidation wired to the existing segment-recompute path. No N+1.
- **After any Python edit**, from `services/server/`:
  `ruff check . --exclude migrations --fix && ruff format . --exclude migrations`.
- **Git commits:** never add `Co-Authored-By` trailers.
- Backend blueprint is mounted at `/api/credit-risk`; frontend axios base is
  `/api`, so the client calls `/credit-risk/analysis/transitions`.

---

### Task 1: Pure core transition-matrix module

**Files:**
- Create: `services/server/project/core/credit_risk/transitions.py`
- Test: `services/server/tests/test_transitions.py`

**Interfaces:**
- Consumes: nothing (pure function over plain data).
- Produces:
  - `build_transition_matrices(client_kmv_rows: Iterable[list[dict]], rating_category: dict[str, int]) -> dict`
    where each KMV row dict has keys `"YEAR"` (int), `"SCENARIO"` (str),
    `"Rating"` (str). Returns:
    ```python
    {
      "scenarios": [str, ...],            # present scenarios, canonical order
      "by_scenario": {
        scenario: {
          "ratings": [str, ...],          # observed notches, best->worst
          "matrix": [[float, ...], ...],  # row-normalised %, rounded 1dp
          "counts": [[int, ...], ...],    # raw transition counts
          "row_totals": [int, ...],       # obs feeding each from-row
          "n_transitions": int,
          "n_clients": int,
          "years": [int, int] | [],       # [min_year, max_year] of used rows
        }
      }
    }
    ```

- [ ] **Step 1: Write the failing tests**

Create `services/server/tests/test_transitions.py`:

```python
"""Pure unit tests for the forecast-implied rating transition matrix.

Imported by file path (bypassing project/__init__.py, which pulls Flask) — same
pattern as tests/test_credit_risk.py.
"""

import importlib.util
import os
import sys

import pytest


def _import_module(name: str, rel_path: str):
    abs_path = os.path.join(os.path.dirname(__file__), "..", rel_path)
    spec = importlib.util.spec_from_file_location(name, abs_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _import_module(
    "transitions", "project/core/credit_risk/transitions.py"
)
build_transition_matrices = _mod.build_transition_matrices

# Category ordering (best -> worst) for the ratings used below.
_CATEGORY = {"Baa1": 10, "Baa2": 11, "Baa3": 12, "Ba1": 13, "Ba2": 14}


def _client(scenario, path):
    """One client's KMV rows: path is [(year, rating), ...] for `scenario`."""
    return [
        {"YEAR": y, "SCENARIO": scenario, "Rating": r} for y, r in path
    ]


def test_basic_two_clients_rows_normalise_to_100():
    clients = [
        _client("Baseline", [(2024, "Baa1"), (2025, "Baa1"), (2026, "Baa2")]),
        _client("Baseline", [(2024, "Baa1"), (2025, "Baa2"), (2026, "Baa2")]),
    ]
    out = build_transition_matrices(clients, _CATEGORY)

    assert out["scenarios"] == ["Baseline"]
    data = out["by_scenario"]["Baseline"]
    # Observed notches ordered best->worst.
    assert data["ratings"] == ["Baa1", "Baa2"]
    # From Baa1: 3 transitions (Baa1->Baa1, Baa1->Baa2, Baa1->Baa2) => 33.3 / 66.7
    baa1_row = data["matrix"][0]
    assert baa1_row == [pytest.approx(33.3, abs=0.05), pytest.approx(66.7, abs=0.05)]
    assert sum(baa1_row) == pytest.approx(100.0, abs=0.2)
    assert data["counts"][0] == [1, 2]
    assert data["row_totals"][0] == 3
    # From Baa2: only Baa2->Baa2 (client 1 year 2025->2026).
    assert data["counts"][1] == [0, 1]
    assert data["n_transitions"] == 4
    assert data["n_clients"] == 2
    assert data["years"] == [2024, 2026]


def test_single_year_client_is_skipped():
    clients = [
        _client("Baseline", [(2024, "Baa1")]),  # no next year -> no transition
        _client("Baseline", [(2024, "Baa2"), (2025, "Baa2")]),
    ]
    out = build_transition_matrices(clients, _CATEGORY)
    data = out["by_scenario"]["Baseline"]
    assert data["ratings"] == ["Baa2"]
    assert data["n_transitions"] == 1
    assert data["n_clients"] == 1


def test_destination_only_rating_appears_with_zero_row():
    # Ba1 only ever appears as a destination (terminal year) -> zero source row.
    clients = [_client("Baseline", [(2024, "Baa3"), (2025, "Ba1")])]
    out = build_transition_matrices(clients, _CATEGORY)
    data = out["by_scenario"]["Baseline"]
    assert data["ratings"] == ["Baa3", "Ba1"]      # ordered by category
    assert data["matrix"][0] == [pytest.approx(0.0), pytest.approx(100.0)]
    assert data["row_totals"] == [1, 0]            # Ba1 has no outgoing obs
    assert data["matrix"][1] == [0.0, 0.0]


def test_scenarios_separated_and_ordered():
    # One client carrying two scenarios; each scenario is tallied independently.
    mixed = [
        {"YEAR": 2024, "SCENARIO": "Baseline", "Rating": "Baa1"},
        {"YEAR": 2025, "SCENARIO": "Baseline", "Rating": "Baa2"},
        {"YEAR": 2024, "SCENARIO": "Adverse", "Rating": "Baa1"},
        {"YEAR": 2025, "SCENARIO": "Adverse", "Rating": "Ba1"},
    ]
    out = build_transition_matrices([mixed], _CATEGORY)
    # Canonical order: Baseline, Adverse, (Severely Adverse) ...
    assert out["scenarios"] == ["Baseline", "Adverse"]
    assert out["by_scenario"]["Adverse"]["ratings"] == ["Baa1", "Ba1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/server && pytest tests/test_transitions.py -v`
Expected: FAIL — `No module named` / `build_transition_matrices` not found
(the module file doesn't exist yet).

- [ ] **Step 3: Write the implementation**

Create `services/server/project/core/credit_risk/transitions.py`:

```python
"""Forecast-implied 1-year rating transition matrices.

Pure computation over KMV rating paths (no Flask/DB), so it is unit-testable by
file-path import like the rest of core/credit_risk. The KMV model assigns each
client a Rating per (year, scenario); counting Rating[t] -> Rating[t+1] across
all clients and row-normalising gives a genuine transition matrix. This is a
*forecast-implied* matrix (from model rating paths), NOT a historical/agency
cohort matrix — the platform has no observed rating-history data.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

# Canonical scenario ordering shared with the rest of the credit-risk UI
# (mirrors routes._all_scenarios / the frontend scenario order).
_SCENARIO_ORDER = {"Baseline": 0, "Adverse": 1, "Severely Adverse": 2}


def _ordered_scenarios(scenarios: Iterable[str]) -> list[str]:
    return sorted(set(scenarios), key=lambda s: (_SCENARIO_ORDER.get(s, 99), s))


def build_transition_matrices(
    client_kmv_rows: Iterable[list[dict]],
    rating_category: dict[str, int],
) -> dict:
    """See module docstring / plan interface for the return shape."""
    # scenario -> {(from, to): count}
    counts: dict[str, dict[tuple[str, str], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    # scenario -> set of contributing client indices
    clients_seen: dict[str, set[int]] = defaultdict(set)
    # scenario -> [min_year, max_year] of rows used in a transition
    year_span: dict[str, list[int]] = {}

    for idx, kmv_rows in enumerate(client_kmv_rows):
        # Group this client's rows by scenario.
        by_scen: dict[str, list[dict]] = defaultdict(list)
        for row in kmv_rows or []:
            scen = row.get("SCENARIO")
            if scen is None:
                continue
            by_scen[str(scen)].append(row)

        for scen, rows in by_scen.items():
            ordered = sorted(rows, key=lambda r: r.get("YEAR", 0))
            if len(ordered) < 2:
                continue
            contributed = False
            for a, b in zip(ordered, ordered[1:]):
                fr, to = a.get("Rating"), b.get("Rating")
                if fr is None or to is None:
                    continue
                counts[scen][(str(fr), str(to))] += 1
                contributed = True
                for y in (a.get("YEAR"), b.get("YEAR")):
                    if y is None:
                        continue
                    span = year_span.get(scen)
                    if span is None:
                        year_span[scen] = [int(y), int(y)]
                    else:
                        span[0] = min(span[0], int(y))
                        span[1] = max(span[1], int(y))
            if contributed:
                clients_seen[scen].add(idx)

    scenarios = _ordered_scenarios(counts.keys())
    by_scenario: dict[str, dict] = {}
    _big = float("inf")

    for scen in scenarios:
        pair_counts = counts[scen]
        observed: set[str] = set()
        for fr, to in pair_counts:
            observed.add(fr)
            observed.add(to)
        ratings = sorted(
            observed, key=lambda r: (rating_category.get(r, _big), r)
        )
        idx_of = {r: i for i, r in enumerate(ratings)}

        n = len(ratings)
        count_grid = [[0] * n for _ in range(n)]
        for (fr, to), c in pair_counts.items():
            count_grid[idx_of[fr]][idx_of[to]] = c

        row_totals = [sum(r) for r in count_grid]
        matrix = [
            [
                round(count_grid[i][j] / row_totals[i] * 100, 1)
                if row_totals[i]
                else 0.0
                for j in range(n)
            ]
            for i in range(n)
        ]

        by_scenario[scen] = {
            "ratings": ratings,
            "matrix": matrix,
            "counts": count_grid,
            "row_totals": row_totals,
            "n_transitions": sum(row_totals),
            "n_clients": len(clients_seen[scen]),
            "years": year_span.get(scen, []),
        }

    return {"scenarios": scenarios, "by_scenario": by_scenario}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/server && pytest tests/test_transitions.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`
Expected: no errors; files unchanged or auto-formatted.

- [ ] **Step 6: Commit**

```bash
git add services/server/project/core/credit_risk/transitions.py services/server/tests/test_transitions.py
git commit -m "feat: pure forecast-implied rating transition matrix core"
```

---

### Task 2: Transitions endpoint + caching + invalidation

**Files:**
- Modify: `services/server/project/api/credit_risk/routes.py` (add helper +
  route in the "analysis" section, after `get_analysis_forecast`).
- Modify: `services/server/project/workers/tasks.py:2094` (add cache-delete line).
- Test: `services/server/tests/test_transitions_endpoint.py`

**Interfaces:**
- Consumes: `build_transition_matrices` (Task 1); existing
  `_get_analysis_run(run_id) -> CreditRiskRun`, `_pd_rating_df(curve) -> DataFrame`,
  module-level `cache`, `db`, `CreditRiskResult`, `json`, `request`, `jsonify`,
  `require_perm`, `credit_risk` blueprint.
- Produces: `GET /api/credit-risk/analysis/transitions?run_id=&scenario=`
  returning `{run_id, scenario, scenarios, ratings, matrix, counts, row_totals,
  n_transitions, n_clients, years}`.

- [ ] **Step 1: Write the failing endpoint tests**

Create `services/server/tests/test_transitions_endpoint.py`:

```python
"""Endpoint tests for GET /api/credit-risk/analysis/transitions."""

import json

from project import db
from project.db_models.credit_models import CreditRiskResult, CreditRiskRun


def _login_as(app, email, role="sysadmin"):
    from project.api.users.models import User

    u = User(email=email, password="Passw0rd!", role=role, name=email)
    u.status = "active"
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post("/api/auth/login", json={"email": email, "password": "Passw0rd!"})
    return c


def _kmv(scenario, path):
    return [
        {"YEAR": y, "SCENARIO": scenario, "Rating": r} for y, r in path
    ]


def _seed_run(run_id="tr-run", active=True, status="success"):
    cr = CreditRiskRun(
        run_id=run_id,
        dataset_id=1,
        is_active=active,
        exposure=1.0,
        discount_rate=0.05,
        lifetime_horizon=5,
        curve="moodys",
        status=status,
    )
    db.session.add(cr)
    db.session.add(
        CreditRiskResult(
            run_id=run_id,
            client_id="C1",
            kmv_json=json.dumps(_kmv("Baseline", [(2024, "Baa1"), (2025, "Baa2")])),
        )
    )
    db.session.add(
        CreditRiskResult(
            run_id=run_id,
            client_id="C2",
            kmv_json=json.dumps(_kmv("Baseline", [(2024, "Baa1"), (2025, "Baa1")])),
        )
    )
    db.session.commit()
    return cr


def test_active_run_returns_matrix(app):
    with app.app_context():
        _seed_run()
        c = _login_as(app, "cr1@x.io")
        resp = c.get("/api/credit-risk/analysis/transitions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["scenario"] == "Baseline"
        assert data["scenarios"] == ["Baseline"]
        assert data["ratings"] == ["Baa1", "Baa2"]
        # From Baa1: 2 obs (->Baa2, ->Baa1) => 50/50.
        assert data["matrix"][0] == [50.0, 50.0]
        assert data["row_totals"][0] == 2
        assert data["n_clients"] == 2


def test_unknown_scenario_returns_422(app):
    with app.app_context():
        _seed_run()
        c = _login_as(app, "cr2@x.io")
        resp = c.get(
            "/api/credit-risk/analysis/transitions?scenario=Nope"
        )
        assert resp.status_code == 422


def test_no_active_run_returns_404(app):
    with app.app_context():
        c = _login_as(app, "cr3@x.io")
        resp = c.get("/api/credit-risk/analysis/transitions")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/server && pytest tests/test_transitions_endpoint.py -v`
Expected: FAIL — 404 route not found for the two 200/422 cases (the
`test_no_active_run_returns_404` may accidentally pass because any unknown route
also 404s; the other two must fail).

- [ ] **Step 3: Add the helper + route in `routes.py`**

Append at the end of `services/server/project/api/credit_risk/routes.py`
(after `get_analysis_forecast`):

```python
# ── Analysis: forecast-implied rating transition matrix ───────────────────────
#
# Built from the active run's KMV rating paths (Rating per year/scenario/client)
# stored in CreditRiskResult.kmv_json. Counting Rating[t] -> Rating[t+1] across
# clients and row-normalising gives a genuine 1-year transition matrix. This is a
# forecast-implied matrix, NOT a historical/agency cohort matrix (the platform
# has no observed rating-history data) — the UI labels it accordingly.


def _transition_payload(cr) -> dict:
    """Cached per-run {scenarios, by_scenario} transition structure.

    Results are immutable for a successful run except via segment recompute,
    which clears this key (see workers/tasks.py) — so a long TTL is safe and
    avoids re-parsing every client's kmv_json on each request/poll.
    """
    from project.core.credit_risk.transitions import build_transition_matrices

    cache_key = f"cr_transitions:{cr.run_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    rows = (
        CreditRiskResult.query.filter_by(run_id=cr.run_id)
        .with_entities(CreditRiskResult.kmv_json)
        .all()
    )
    client_kmv_rows = [json.loads(r.kmv_json or "[]") for r in rows]

    pd_df = _pd_rating_df(cr.curve)
    rating_category = dict(zip(pd_df["Rating"], pd_df["Category"]))

    payload = build_transition_matrices(client_kmv_rows, rating_category)
    cache.set(cache_key, payload, timeout=3600)
    return payload


@credit_risk.get("/analysis/transitions")
@require_perm("credit_risk:read")
def get_analysis_transitions():
    try:
        cr = _get_analysis_run(request.args.get("run_id"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    payload = _transition_payload(cr)
    scenarios = payload["scenarios"]
    if not scenarios:
        return jsonify(
            {"error": "No transition data for the active analysis run."}
        ), 422

    requested = request.args.get("scenario")
    if requested and requested not in scenarios:
        return jsonify(
            {"error": f"Scenario '{requested}' is not present in this run."}
        ), 422
    scenario = requested or (
        "Baseline" if "Baseline" in scenarios else scenarios[0]
    )

    data = payload["by_scenario"][scenario]
    if not data["ratings"]:
        return jsonify(
            {"error": "No transition data for the active analysis run."}
        ), 422

    return jsonify(
        {
            "run_id": cr.run_id,
            "scenario": scenario,
            "scenarios": scenarios,
            **data,
        }
    ), 200
```

- [ ] **Step 4: Wire cache invalidation in the worker**

In `services/server/project/workers/tasks.py`, find the segment-recompute
invalidation block (around line 2091-2096):

```python
            try:
                from project import cache

                cache.delete(f"cr_run_results:{cr_run_id}")
            except Exception:
                pass
```

Change it to also drop the transitions cache:

```python
            try:
                from project import cache

                cache.delete(f"cr_run_results:{cr_run_id}")
                cache.delete(f"cr_transitions:{cr_run_id}")
            except Exception:
                pass
```

- [ ] **Step 5: Run the endpoint tests**

Run: `cd services/server && pytest tests/test_transitions_endpoint.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Lint**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add services/server/project/api/credit_risk/routes.py services/server/project/workers/tasks.py services/server/tests/test_transitions_endpoint.py
git commit -m "feat: transitions endpoint with per-run cache + invalidation"
```

---

### Task 3: Frontend — API client method + real Transitions view

**Files:**
- Modify: `services/client/src/api/creditRiskAPI.js` (add `analysisTransitions`).
- Modify: `services/client/src/views/credit_risk/CreditRiskTransitions.vue`
  (full rewrite of `<script setup>` + template; keep `cellStyle` intent).

**Interfaces:**
- Consumes: `GET /credit-risk/analysis/transitions` (Task 2) → `{run_id,
  scenario, scenarios, ratings, matrix, counts, row_totals, n_transitions,
  n_clients, years}`.
- Produces: routed view at `/credit-risk/transitions` (no downstream consumers).

- [ ] **Step 1: Add the API client method**

In `services/client/src/api/creditRiskAPI.js`, add after `analysisForecast`
(inside the object, keep the trailing comma style):

```js
  analysisForecast: (params)       => httpClient.get('/credit-risk/analysis/forecast', { params }),
  analysisTransitions: (params = {}) => httpClient.get('/credit-risk/analysis/transitions', { params }),
```

- [ ] **Step 2: Rewrite `CreditRiskTransitions.vue`**

Replace the entire contents of
`services/client/src/views/credit_risk/CreditRiskTransitions.vue` with:

```vue
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import creditRiskAPI from '@/api/creditRiskAPI'
import PageHeader from '@/components/ui/PageHeader.vue'

const router = useRouter()

const loading      = ref(false)
const noActiveRun  = ref(false)
const errorMessage = ref(null)

const scenarios     = ref([])       // available scenario names
const scenario      = ref(null)     // selected
const ratings       = ref([])       // observed notches (best -> worst)
const matrix        = ref([])       // % rows
const counts        = ref([])       // raw transition counts
const rowTotals     = ref([])       // obs feeding each from-row
const nTransitions  = ref(0)
const nClients      = ref(0)
const years         = ref([])       // [minYear, maxYear]

const yearLabel = computed(() =>
  years.value.length === 2 ? `${years.value[0]}–${years.value[1]}` : ''
)

// Per-row max drives the off-diagonal alpha ramp: real rows are normalised to
// 100 %, so scaling against the row's own max keeps migration contrast readable
// whether a row is concentrated on the diagonal or spread out. Diagonal keeps
// the ink/yellow treatment.
function cellStyle(val, rowIdx, colIdx) {
  if (rowIdx === colIdx) {
    return { background: 'var(--ink)', color: 'var(--yellow)' }
  }
  const row = matrix.value[rowIdx] || []
  const rowMax = Math.max(1, ...row.filter((_, j) => j !== rowIdx))
  const alpha = Math.min(0.08 + (val / rowMax) * 0.8, 0.85)
  return {
    background: `rgba(46, 46, 56, ${alpha.toFixed(2)})`,
    color: alpha > 0.45 ? '#FFFFFF' : 'var(--text-color)',
  }
}

function cellTitle(rowIdx, colIdx) {
  const c = counts.value?.[rowIdx]?.[colIdx] ?? 0
  const t = rowTotals.value?.[rowIdx] ?? 0
  return `${c} of ${t} transitions`
}

async function fetchTransitions() {
  loading.value = true
  errorMessage.value = null
  try {
    const params = scenario.value ? { scenario: scenario.value } : {}
    const { data } = await creditRiskAPI.analysisTransitions(params)
    scenarios.value    = data.scenarios ?? []
    scenario.value     = data.scenario
    ratings.value      = data.ratings ?? []
    matrix.value       = data.matrix ?? []
    counts.value       = data.counts ?? []
    rowTotals.value    = data.row_totals ?? []
    nTransitions.value = data.n_transitions ?? 0
    nClients.value     = data.n_clients ?? 0
    years.value        = data.years ?? []
    noActiveRun.value  = false
  } catch (e) {
    ratings.value = []
    matrix.value = []
    if (e?.response?.status === 404) {
      noActiveRun.value = true
    } else {
      errorMessage.value = e?.response?.data?.error ?? e.message
    }
  } finally {
    loading.value = false
  }
}

function selectScenario(s) {
  if (s === scenario.value) return
  scenario.value = s
  fetchTransitions()
}

onMounted(fetchTransitions)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="ANALYSIS"
      title="Transitions"
      subtitle="Forecast-implied 1-year credit-grade transition probabilities (%) from the active run's KMV rating paths. Ink diagonal = stable; gray intensity = migration size."
    >
      <template #actions>
        <span v-if="ratings.length" class="font-mono meta-caption">
          {{ nClients }} clients &middot; {{ nTransitions }} transitions
          <template v-if="yearLabel"> &middot; {{ yearLabel }}</template>
        </span>
      </template>
    </PageHeader>

    <!-- Scenario toggle -->
    <div v-if="scenarios.length" class="metric-row">
      <span class="metric-label">SCENARIO</span>
      <div
        v-for="s in scenarios"
        :key="s"
        class="metric-chip"
        :class="{ active: scenario === s }"
        @click="selectScenario(s)"
      >{{ s }}</div>
    </div>

    <!-- No active run -->
    <div v-if="noActiveRun && !loading" class="panel flex flex-column align-items-center justify-content-center gap-3" style="height: 22rem">
      <i class="pi pi-sitemap text-4xl text-color-secondary opacity-50" />
      <div class="text-center">
        <div class="text-sm font-medium mb-1">No active analysis run</div>
        <div class="text-xs text-color-secondary">Set an active run in Job History to view rating transitions.</div>
      </div>
      <Button label="Job History" icon="pi pi-list" size="small" @click="router.push({ name: 'jobs_history' })" />
    </div>

    <!-- Error / no transition data -->
    <div v-else-if="errorMessage && !loading" class="panel flex flex-column align-items-center justify-content-center gap-3" style="height: 22rem">
      <i class="pi pi-exclamation-circle text-4xl text-color-secondary opacity-50" />
      <div class="text-center" style="max-width: 28rem">
        <div class="text-sm font-medium mb-1">Transition data unavailable</div>
        <div class="text-xs text-color-secondary">{{ errorMessage }}</div>
      </div>
      <Button label="Job History" icon="pi pi-list" size="small" @click="router.push({ name: 'jobs_history' })" />
    </div>

    <!-- Loading -->
    <div v-else-if="loading" class="flex justify-content-center align-items-center" style="height: 12rem">
      <i class="pi pi-spin pi-spinner text-3xl text-color-secondary" />
    </div>

    <!-- Matrix -->
    <div v-else-if="ratings.length" class="panel">
      <div class="matrix-grid matrix-grid--head">
        <div>FROM &#8594; TO</div>
        <div v-for="r in ratings" :key="r" class="ta-center">{{ r }}</div>
      </div>
      <div v-for="(row, ri) in matrix" :key="ri" class="matrix-grid matrix-grid--row">
        <div class="row-label">{{ ratings[ri] }}</div>
        <div
          v-for="(val, ci) in row" :key="ci"
          class="font-mono cell"
          :style="cellStyle(val, ri, ci)"
          :title="cellTitle(ri, ci)"
        >{{ val.toFixed(1) }}%</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 16px;
}

.meta-caption { font-size: 11.5px; color: var(--text-color-muted); }

.metric-row { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.metric-label { font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: var(--text-color-muted); }
.metric-chip {
  padding: 7px 12px;
  border-radius: 2px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--surface-border-input);
  background: #FFFFFF;
  color: var(--text-color-secondary);
}
.metric-chip:hover { border-color: var(--ink); }
.metric-chip.active { background: var(--ink); color: #FFFFFF; border-color: var(--ink); }

.matrix-grid {
  display: grid;
  grid-template-columns: 90px repeat(v-bind('ratings.length || 8'), 1fr);
  column-gap: 8px;
  align-items: center;
}
.matrix-grid--head {
  height: 36px;
  border-bottom: 2px solid var(--ink);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--text-color-muted);
}
.matrix-grid--row { padding: 2px 0; }
.ta-center { text-align: center; }
.row-label { font-size: 13px; font-weight: 600; }
.cell {
  margin: 2px 0;
  padding: 11px 0;
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  border-radius: 2px;
}
</style>
```

Notes for the implementer:
- `Button` is registered globally (used unregistered in `CreditRiskHeatmap.vue`);
  do not add an import for it.
- The `v-bind('ratings.length || 8')` in scoped CSS mirrors the Heatmap's
  `v-bind('heat?.years.length || 5')` pattern — this is valid PrimeVue-v3-era
  Vue 3 SFC syntax already used in this repo.

- [ ] **Step 3: Verify in the running app (preview workflow)**

Start/reuse the client dev server, then verify against a backend with at least
one **successful, active** credit-risk run (create one via the New Analysis flow
if none exists):

1. Navigate to `/credit-risk/transitions`.
2. Confirm the matrix renders with a **Moody's-notch axis** (e.g. Baa1/Baa2/…),
   **not** AAA…D, and diagonal cells show the ink/yellow treatment.
3. Confirm the SCENARIO chips list the run's scenarios; clicking Adverse /
   Severely Adverse refetches and re-renders.
4. Hover a cell → tooltip shows `"<count> of <total> transitions"`.
5. Check the browser console/network: `GET /api/credit-risk/analysis/transitions`
   returns 200 with the documented shape; no console errors.
6. With no active run (unset it in Job History, or point at a fresh DB), confirm
   the "No active analysis run" empty state shows instead of any demo numbers.

Capture a screenshot of the rendered real matrix as proof.

- [ ] **Step 4: Commit**

```bash
git add services/client/src/api/creditRiskAPI.js services/client/src/views/credit_risk/CreditRiskTransitions.vue
git commit -m "feat: render real forecast-implied transition matrix"
```

---

## Self-Review

**Spec coverage:**
- Backend endpoint returning the real matrix → Task 2. ✓
- Compute from KMV rating paths (no rating-history table) → Task 1. ✓
- Observed-notch axis ordered by category → Task 1 (`build_transition_matrices`
  ordering) + verified in Task 3 step 3. ✓
- Scenario toggle, default Baseline → Task 2 (default logic) + Task 3 (chips). ✓
- Empty states (no active run / no data) → Task 2 (404/422) + Task 3 (panels). ✓
- Keep ink-diagonal / monochrome-ramp rendering → Task 3 `cellStyle`. ✓
- Sample-size honesty (`counts`/`row_totals`) → Task 1 output + Task 3 tooltip. ✓
- Caching per run + invalidation at tasks.py:2094 → Task 2 steps 3–4. ✓
- Honest "forecast-implied" labelling → Task 3 subtitle. ✓
- No migration → confirmed; no schema task. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full
code. ✓

**Type consistency:** `build_transition_matrices(client_kmv_rows, rating_category)`
returns `{scenarios, by_scenario}`; consumed identically in `_transition_payload`
(Task 2) and the response keys (`ratings, matrix, counts, row_totals,
n_transitions, n_clients, years`) match exactly what the Vue view reads in Task 3.
Cache key `cr_transitions:{run_id}` is identical in the setter (Task 2 step 3) and
the invalidator (Task 2 step 4). ✓
