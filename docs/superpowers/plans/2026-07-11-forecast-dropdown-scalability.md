# Forecast Dropdown Distinct Scalability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Financial Forecast results-table filter dropdowns (`/api/forecast-runs/<run_id>/results/distinct`) scale to large runs by (1) caching per-run facets and (2) promoting hot categorical fields out of `meta_json` into indexed columns answered by SQL `DISTINCT` — with a reproducible benchmark that measures performance before and after each option.

**Architecture:** Today every filterable column fires one distinct request on table load ([CommonDataTable.vue:101](../../../services/client/src/components/Table/CommonDataTable.vue) `resolveFilterKinds` → `Promise.all`). Each request calls `results_df(fr)` — `SELECT *` for the whole run, then `json.loads(meta_json)` per row into pandas — then `distinct_values` in memory ([forecast_runs.py:155](../../../services/server/project/services/forecast_runs.py), [table_query.py:105](../../../services/server/project/core/table_query.py)). Cost is `D × O(N)` per page load with N = rows-in-run. We introduce a single service seam `distinct_for_column(fr, column)` that the route and the benchmark both call, then swap its internals: **Option 1** wraps it in a per-run facet cache (immutable `run_id` ⇒ ~100% hit rate, no invalidation risk beyond segment re-score); **Option 2** promotes `sector, subsector, country, scenario` to indexed columns (mirroring the existing `segment_key` denormalization at [forecast_models.py:112](../../../services/server/project/db_models/forecast_models.py)) and answers those columns with `SELECT DISTINCT … LIMIT 31`.

**Tech Stack:** Python 3.11 / Flask, Flask-SQLAlchemy 3, Flask-Migrate 4 (Alembic), Flask-Caching (SimpleCache in test/`testing`, RedisCache in dev/prod), pandas 2.2, pytest; frontend Vue 3 + Vitest 2.

## Global Constraints

- **Production-grade by default.** No N+1, index filtered columns, keep heavy work bounded. (CLAUDE.md §5)
- **`run_id` (UUID) is immutable.** A rerun creates a new run; never mutate an existing one. Facet caches key on `run_id` and are safe to cache indefinitely for `status == "success"` runs. (CLAUDE.md §5)
- **Do not break serialised model pickles** in MinIO. (No change here — we only touch `forecast_run_results`.)
- **After any Python edit**, from `services/server/`: `ruff check . --exclude migrations --fix && ruff format . --exclude migrations`.
- **Auth & RBAC:** the distinct route stays `@require_perm("forecast:read")`. (CLAUDE.md §5)
- **Never add `Co-Authored-By` trailers.** Only commit when explicitly told. (CLAUDE.md §5 — this plan's `git commit` steps are still written out; the executor runs them per the executing-plans checkpoints, but the trailer rule holds.)
- **Migration head is `b1c3d5e7f9a1`.** New migrations chain from it (or from the previous plan-added migration if executed in sequence).
- **Benchmark DB fidelity:** tests default to in-memory SQLite ([config.py:171](../../../services/server/project/config.py)). SQLite shows the *pandas-load elimination* but **not** MSSQL index behavior. The authoritative before/after numbers for Option 2 MUST be captured against the Docker MSSQL stack (`CONFIG_NAME=dev`, `docker compose -f docker-compose.debug.yml up -d mssql`). The benchmark script reads whatever DB the active config points at.

---

## File Structure

**Backend — new:**
- `services/server/benchmarks/__init__.py` — package marker (empty).
- `services/server/benchmarks/bench_forecast_distinct.py` — standalone seed + timing harness; writes JSON results to `benchmarks/results/`.
- `services/server/benchmarks/results/` — captured before/after JSON (git-ignored except a `.gitkeep`).
- `services/server/tests/test_forecast_distinct.py` — correctness tests for `distinct_for_column` (behavior must be identical across all three implementations).

**Backend — modified:**
- `services/server/project/services/forecast_runs.py` — add `distinct_for_column`, `_run_facets`, `invalidate_facets`, `PROMOTED_DIMENSIONS`, `promoted_dims_from_meta`.
- `services/server/project/api/forecast_runs/routes.py` — route delegates to `distinct_for_column`.
- `services/server/project/workers/forecast.py` — write-path populates promoted columns; recompute path invalidates facet cache.
- `services/server/project/db_models/forecast_models.py` — add `sector/subsector/country/scenario` columns + composite indexes.
- `services/server/migrations/versions/<rev>_add_forecast_facet_columns.py` — new migration (Option 2).

**Frontend — modified:**
- `services/client/src/views/jobs/parts/resultColumns.js` — mark numeric columns `filterable: false` so they stop firing probe requests.
- `services/client/src/views/jobs/parts/__tests__/resultColumns.spec.js` — new Vitest spec.

---

## Phase 0 — Benchmark harness & single seam (do first; no behavior change)

### Task 0: Introduce `distinct_for_column` seam and refactor the route to use it

**Files:**
- Modify: `services/server/project/services/forecast_runs.py`
- Modify: `services/server/project/api/forecast_runs/routes.py:222-233`
- Test: `services/server/tests/test_forecast_distinct.py`

**Interfaces:**
- Produces: `forecast_run_service.distinct_for_column(fr: ForecastRun, column: str) -> dict` returning `{"values": list[str], "truncated": bool}` — identical shape to `table_query.distinct_values`. This is the seam all later tasks swap.

- [ ] **Step 1: Write the failing test**

Create `services/server/tests/test_forecast_distinct.py`:

```python
"""distinct_for_column must return the same {values, truncated} shape regardless
of which implementation (df / cache / SQL) backs it. Seeded via bulk insert."""
import json

import pytest

from project import db
from project.db_models.forecast_models import ForecastRun, ForecastRunResult
from project.services import forecast_runs as svc


def _seed_run(status="success", n_per_sector=5):
    fr = ForecastRun(run_id="bench-run-1", status=status)
    db.session.add(fr)
    db.session.flush()
    sectors = ["Energy", "Financials", "Tech"]
    rows = []
    for i in range(n_per_sector * len(sectors)):
        sector = sectors[i % len(sectors)]
        rows.append(
            {
                "forecast_run_id": fr.id,
                "date": f"2030-{(i % 12) + 1:02d}-01",
                "predicted": float(i),
                "segment_key": f"seg_{sector}",
                "meta_json": json.dumps(
                    {"sector": sector, "scenario": "Baseline", "segment_key": f"seg_{sector}"}
                ),
            }
        )
    db.session.bulk_insert_mappings(ForecastRunResult, rows)
    db.session.commit()
    return fr


def test_distinct_for_column_returns_sorted_capped_values(app):
    with app.app_context():
        fr = _seed_run()
        out = svc.distinct_for_column(fr, "sector")
        assert out["values"] == ["Energy", "Financials", "Tech"]
        assert out["truncated"] is False


def test_distinct_for_column_unknown_column_is_empty(app):
    with app.app_context():
        fr = _seed_run()
        out = svc.distinct_for_column(fr, "does_not_exist")
        assert out == {"values": [], "truncated": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py -v`
Expected: FAIL with `AttributeError: module 'project.services.forecast_runs' has no attribute 'distinct_for_column'`.

- [ ] **Step 3: Add the seam in `services/server/project/services/forecast_runs.py`**

Add these imports near the top if not present (`table_query` is already imported by callers; verify):

```python
from project.core import table_query
```

Add after `results_df` (around line 169):

```python
def distinct_for_column(fr: ForecastRun, column: str) -> dict:
    """Distinct values for one result column, for a filter dropdown.

    Single seam used by the route and the benchmark. Its internals are swapped
    across the scalability options (df scan → cache → indexed SQL); the return
    shape ``{"values": [...], "truncated": bool}`` is invariant.
    """
    df = results_df(fr)
    return table_query.distinct_values(df, column)
```

- [ ] **Step 4: Point the route at the seam**

In `services/server/project/api/forecast_runs/routes.py`, replace the body of `get_results_distinct` (lines 232-233):

```python
    df = forecast_run_service.results_df(fr)
    return jsonify(table_query.distinct_values(df, column)), 200
```

with:

```python
    return jsonify(forecast_run_service.distinct_for_column(fr, column)), 200
```

(Leave the `column` empty-guard above it unchanged. `table_query` may now be an unused import in this file — run ruff in Step 6 to catch it; keep it only if other routes here use it.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Lint**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`
Expected: no errors (import cleanup applied if needed).

- [ ] **Step 7: Commit**

```bash
git add services/server/project/services/forecast_runs.py services/server/project/api/forecast_runs/routes.py services/server/tests/test_forecast_distinct.py
git commit -m "refactor(forecast): route distinct through distinct_for_column seam"
```

---

### Task 1: Build the benchmark harness

**Files:**
- Create: `services/server/benchmarks/__init__.py`
- Create: `services/server/benchmarks/bench_forecast_distinct.py`
- Create: `services/server/benchmarks/results/.gitkeep`

**Interfaces:**
- Consumes: `forecast_run_service.distinct_for_column` (Task 0).
- Produces: CLI `python -m benchmarks.bench_forecast_distinct --rows N --label LABEL` → prints a per-column + total timing table and writes `benchmarks/results/<LABEL>.json`.

- [ ] **Step 1: Create the package marker**

Create `services/server/benchmarks/__init__.py` (empty file).

- [ ] **Step 2: Create the results dir keep-file**

Create `services/server/benchmarks/results/.gitkeep` (empty file).

- [ ] **Step 3: Write the harness**

Create `services/server/benchmarks/bench_forecast_distinct.py`:

```python
"""Benchmark the forecast results distinct-dropdown path.

Seeds ONE forecast run with --rows result rows across realistic low-cardinality
dimensions, then times ``forecast_run_service.distinct_for_column`` for each
column the frontend probes on table load (simulating CommonDataTable's parallel
resolveFilterKinds). Reports cold + warm totals and writes a JSON result.

Run against SQLite (fast, shows pandas-load elimination):
    cd services/server && python -m benchmarks.bench_forecast_distinct --rows 200000 --label before-option1

Run against MSSQL (authoritative index numbers for Option 2):
    docker compose -f docker-compose.debug.yml up -d mssql
    cd services/server && CONFIG_NAME=dev python -m benchmarks.bench_forecast_distinct --rows 2000000 --label after-option2
"""
import argparse
import json
import os
import statistics
import time
import uuid
from pathlib import Path

os.environ.setdefault("CONFIG_NAME", "testing")

from project import cache, create_app, db  # noqa: E402
from project.db_models.forecast_models import ForecastRun, ForecastRunResult  # noqa: E402
from project.services import forecast_runs as svc  # noqa: E402

# Columns CommonDataTable probes on load for a segmented forecast run.
PROBE_COLUMNS = ["sector", "subsector", "country", "scenario", "segment_key", "date"]
SECTORS = ["Energy", "Financials", "Tech", "Health", "Industrials", "Utilities"]
SUBSECTORS = [f"sub_{i}" for i in range(30)]
COUNTRIES = ["US", "GB", "DE", "FR", "JP", "SG", "AU", "CA"]
SCENARIOS = ["Baseline", "Adverse", "Severely Adverse"]
RESULTS_DIR = Path(__file__).parent / "results"


def seed(fr_id: int, n_rows: int, chunk: int = 20_000) -> None:
    buf = []
    for i in range(n_rows):
        sector = SECTORS[i % len(SECTORS)]
        seg = f"seg_{sector}"
        meta = {
            "sector": sector,
            "subsector": SUBSECTORS[i % len(SUBSECTORS)],
            "country": COUNTRIES[i % len(COUNTRIES)],
            "scenario": SCENARIOS[i % len(SCENARIOS)],
            "segment_key": seg,
        }
        buf.append(
            {
                "forecast_run_id": fr_id,
                "date": f"20{30 + (i % 10)}-{(i % 12) + 1:02d}-01",
                "predicted": float(i % 1000),
                "segment_key": seg,
                "meta_json": json.dumps(meta),
            }
        )
        if len(buf) >= chunk:
            db.session.bulk_insert_mappings(ForecastRunResult, buf)
            db.session.commit()
            buf = []
    if buf:
        db.session.bulk_insert_mappings(ForecastRunResult, buf)
        db.session.commit()


def time_probe(fr, repeats: int = 3) -> dict:
    """Median wall-clock (ms) per column and the summed 'page-load' total."""
    per_col = {}
    for col in PROBE_COLUMNS:
        samples = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            svc.distinct_for_column(fr, col)
            samples.append((time.perf_counter() - t0) * 1000)
        per_col[col] = round(statistics.median(samples), 2)
    return {"per_column_ms": per_col, "page_total_ms": round(sum(per_col.values()), 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=200_000)
    ap.add_argument("--label", required=True)
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        db.create_all()
        cache.clear()
        fr = ForecastRun(run_id=f"bench-{uuid.uuid4()}", status="success")
        db.session.add(fr)
        db.session.flush()
        print(f"Seeding {args.rows:,} rows…")
        t0 = time.perf_counter()
        seed(fr.id, args.rows)
        print(f"  seeded in {time.perf_counter() - t0:.1f}s")

        cache.delete(f"forecast_facets:{fr.run_id}")  # ensure a true cold read
        cold = time_probe(fr)
        warm = time_probe(fr)  # second pass — hits any cache introduced by an option

        result = {
            "label": args.label,
            "config": os.environ.get("CONFIG_NAME"),
            "db": str(db.engine.url).split("://", 1)[0],
            "rows": args.rows,
            "cold": cold,
            "warm": warm,
        }
        RESULTS_DIR.mkdir(exist_ok=True)
        out = RESULTS_DIR / f"{args.label}.json"
        out.write_text(json.dumps(result, indent=2))

        print(f"\n=== {args.label}  ({result['db']}, {args.rows:,} rows) ===")
        print(f"{'column':<14}{'cold ms':>10}{'warm ms':>10}")
        for col in PROBE_COLUMNS:
            print(f"{col:<14}{cold['per_column_ms'][col]:>10}{warm['per_column_ms'][col]:>10}")
        print(f"{'PAGE TOTAL':<14}{cold['page_total_ms']:>10}{warm['page_total_ms']:>10}")
        print(f"\nwrote {out}")

        # Clean up so repeat runs don't accumulate rows in a persistent DB.
        ForecastRunResult.query.filter_by(forecast_run_id=fr.id).delete()
        db.session.query(ForecastRun).filter_by(id=fr.id).delete()
        db.session.commit()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Smoke-test the harness on a small run**

Run: `cd services/server && python -m benchmarks.bench_forecast_distinct --rows 5000 --label smoke`
Expected: prints a timing table with 6 columns + `PAGE TOTAL`; writes `benchmarks/results/smoke.json`; exits 0.

- [ ] **Step 5: Git-ignore the results payloads (keep the dir)**

Append to `services/server/.gitignore` (create it if absent):

```
benchmarks/results/*.json
```

- [ ] **Step 6: Commit**

```bash
git add services/server/benchmarks services/server/.gitignore
git commit -m "test(forecast): add distinct-dropdown benchmark harness"
```

---

### Task 2: Capture the Option-0 baseline (current df-scan implementation)

**Files:** none modified — this task produces measurements committed as a note.

- [ ] **Step 1: Baseline on SQLite (relative pandas-load cost)**

Run: `cd services/server && python -m benchmarks.bench_forecast_distinct --rows 200000 --label baseline-sqlite`
Expected: `cold` and `warm` page totals are similar and both scale with rows (no cache yet). Record the printed `PAGE TOTAL`.

- [ ] **Step 2: Baseline on MSSQL (authoritative)**

```bash
docker compose -f docker-compose.debug.yml up -d mssql
cd services/server && CONFIG_NAME=dev python -m benchmarks.bench_forecast_distinct --rows 500000 --label baseline-mssql
```
Expected: page totals dominated by `SELECT *` transfer + per-row `json.loads`. Record `PAGE TOTAL`.

- [ ] **Step 3: Record the baseline**

Create `services/server/benchmarks/BASELINE.md` with a table:

```markdown
# Forecast distinct benchmark — baseline (df scan)

| DB     | rows    | cold page ms | warm page ms |
|--------|---------|--------------|--------------|
| sqlite | 200,000 | <fill>       | <fill>       |
| mssql  | 500,000 | <fill>       | <fill>       |

Method: `python -m benchmarks.bench_forecast_distinct`. Probed columns:
sector, subsector, country, scenario, segment_key, date (6 parallel probes on load).
```

Fill `<fill>` from Steps 1-2.

- [ ] **Step 4: Commit**

```bash
git add services/server/benchmarks/BASELINE.md
git commit -m "test(forecast): record df-scan distinct baseline numbers"
```

---

## Phase 1 — Option 1: Per-run facet cache

### Task 3: Cache all-column facets per run behind the seam

**Files:**
- Modify: `services/server/project/services/forecast_runs.py`
- Test: `services/server/tests/test_forecast_distinct.py`

**Interfaces:**
- Produces: `forecast_run_service._run_facets(fr) -> dict[str, dict]` (column → `{values, truncated}`); `forecast_run_service.invalidate_facets(run_id: str) -> None`. `distinct_for_column` now reads from `_run_facets`.

- [ ] **Step 1: Write the failing test (cache is used and correct)**

Append to `services/server/tests/test_forecast_distinct.py`:

```python
def test_facets_cached_after_first_call(app, monkeypatch):
    with app.app_context():
        fr = _seed_run()
        calls = {"n": 0}
        real_results_df = svc.results_df

        def counting_results_df(fr_):
            calls["n"] += 1
            return real_results_df(fr_)

        monkeypatch.setattr(svc, "results_df", counting_results_df)

        # Two different columns, two calls — but only ONE df load (facets cached).
        svc.distinct_for_column(fr, "sector")
        svc.distinct_for_column(fr, "scenario")
        assert calls["n"] == 1


def test_inprogress_run_not_cached(app, monkeypatch):
    with app.app_context():
        fr = _seed_run(status="running")
        calls = {"n": 0}
        real_results_df = svc.results_df

        def counting_results_df(fr_):
            calls["n"] += 1
            return real_results_df(fr_)

        monkeypatch.setattr(svc, "results_df", counting_results_df)
        svc.distinct_for_column(fr, "sector")
        svc.distinct_for_column(fr, "scenario")
        assert calls["n"] == 2  # not cached while status != success
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py -v -k "cached or inprogress"`
Expected: FAIL — `test_facets_cached_after_first_call` sees `calls['n'] == 2`.

- [ ] **Step 3: Implement the facet cache**

In `services/server/project/services/forecast_runs.py`, add the import:

```python
from project import cache, db
```

(Adjust to merge with the existing `from project import …` line.) Replace `distinct_for_column` (from Task 0) with:

```python
_FACETS_KEY = "forecast_facets:{run_id}"


def _run_facets(fr: ForecastRun) -> dict:
    """All-column distinct facets for a run, computed once and cached.

    ``run_id`` is immutable, so a successful run's facets never change (a segment
    re-score changes ``predicted``, not dimension membership); we cache them for
    an hour and invalidate defensively on re-score. In-progress runs are still
    accumulating rows, so we never cache those.
    """
    key = _FACETS_KEY.format(run_id=fr.run_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    df = results_df(fr)
    facets = {col: table_query.distinct_values(df, col) for col in df.columns}
    if fr.status == "success":
        cache.set(key, facets, timeout=3600)
    return facets


def distinct_for_column(fr: ForecastRun, column: str) -> dict:
    """Distinct values for one result column, for a filter dropdown.

    Single seam used by the route and the benchmark. Backed by a per-run facet
    cache so N dropdown probes on table load cost one df scan (cold) then O(1).
    """
    return _run_facets(fr).get(column, {"values": [], "truncated": False})


def invalidate_facets(run_id: str) -> None:
    """Drop a run's cached facets — call after any write that could change its
    result rows (segment re-score)."""
    cache.delete(_FACETS_KEY.format(run_id=run_id))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py -v`
Expected: PASS (all, including the Task-0 correctness tests — behavior is unchanged, only caching added).

- [ ] **Step 5: Lint**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add services/server/project/services/forecast_runs.py services/server/tests/test_forecast_distinct.py
git commit -m "perf(forecast): cache per-run distinct facets behind the seam"
```

---

### Task 4: Invalidate facets on segment re-score

**Files:**
- Modify: `services/server/project/workers/forecast.py`
- Test: `services/server/tests/test_forecast_distinct.py`

**Interfaces:**
- Consumes: `forecast_run_service.invalidate_facets` (Task 3).

- [ ] **Step 1: Write the failing test**

Append to `services/server/tests/test_forecast_distinct.py`:

```python
def test_invalidate_facets_clears_cache(app):
    from project import cache

    with app.app_context():
        fr = _seed_run()
        svc.distinct_for_column(fr, "sector")  # populate cache
        assert cache.get(f"forecast_facets:{fr.run_id}") is not None
        svc.invalidate_facets(fr.run_id)
        assert cache.get(f"forecast_facets:{fr.run_id}") is None
```

- [ ] **Step 2: Run to verify it passes already for the helper, then wire the call site**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py::test_invalidate_facets_clears_cache -v`
Expected: PASS (the helper exists from Task 3). Now ensure the re-score path calls it.

- [ ] **Step 3: Call `invalidate_facets` after a segment re-score commits**

In `services/server/project/workers/forecast.py`, find `recompute_forecast_run_segment` (around line 103) and its caller that commits the re-score (the `with app_session() as s:` block ending near line 364). Immediately after the successful commit of the re-scored rows, add:

```python
        from project.services import forecast_runs as forecast_run_service

        forecast_run_service.invalidate_facets(run_id)
```

Place it after the transaction that writes the new segment rows and sets `r.status = "success"` commits, so a stale facet set can't survive a re-score. Use the `run_id` already in scope.

- [ ] **Step 4: Run the worker + distinct test suites**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py tests/test_segment_recompute.py -v`
Expected: PASS (no regression in re-score behavior).

- [ ] **Step 5: Lint**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add services/server/project/workers/forecast.py services/server/tests/test_forecast_distinct.py
git commit -m "fix(forecast): invalidate distinct facet cache on segment re-score"
```

---

### Task 5: Measure Option 1 (after) and compare

**Files:** Modify `services/server/benchmarks/BASELINE.md` → add an Option-1 section.

- [ ] **Step 1: Re-run the benchmark (SQLite + MSSQL)**

```bash
cd services/server && python -m benchmarks.bench_forecast_distinct --rows 200000 --label option1-sqlite
docker compose -f docker-compose.debug.yml up -d mssql
cd services/server && CONFIG_NAME=dev python -m benchmarks.bench_forecast_distinct --rows 500000 --label option1-mssql
```
Expected: `cold` page total ≈ baseline (one df scan still paid on first probe), but `warm` page total collapses to ~O(1) (cache hits). The warm/baseline ratio is the Option-1 win for repeat page loads.

- [ ] **Step 2: Append results to `BASELINE.md`**

```markdown
## Option 1 — per-run facet cache

| DB     | rows    | cold page ms | warm page ms | warm speedup vs baseline |
|--------|---------|--------------|--------------|--------------------------|
| sqlite | 200,000 | <fill>       | <fill>       | <baseline_warm/option1_warm>x |
| mssql  | 500,000 | <fill>       | <fill>       | <fill>x |

Takeaway: eliminates the D-1 redundant scans on first load and ~100% of the
cost on every subsequent visit (immutable run ⇒ near-100% hit rate). Cold path
still O(N) — addressed by Option 2.
```

- [ ] **Step 3: Commit**

```bash
git add services/server/benchmarks/BASELINE.md
git commit -m "test(forecast): record Option 1 (facet cache) benchmark"
```

---

## Phase 2 — Option 2: Promote hot dimensions to indexed columns

### Task 6: Add promoted columns + composite indexes (model + migration)

**Files:**
- Modify: `services/server/project/db_models/forecast_models.py:112-120`
- Create: `services/server/migrations/versions/c3d5e7f9a1b3_add_forecast_facet_columns.py`

**Interfaces:**
- Produces: `ForecastRunResult.sector/subsector/country/scenario` columns (nullable `String`), each with a composite index `(forecast_run_id, <col>)`.

- [ ] **Step 1: Add columns + indexes to the model**

In `services/server/project/db_models/forecast_models.py`, extend `ForecastRunResult`. After the `segment_key` column (line 112) add:

```python
    # Denormalised copies of low-cardinality meta_json dimensions so filter
    # dropdowns can be answered by an indexed SELECT DISTINCT instead of loading
    # and JSON-parsing the whole run into pandas. Mirror the segment_key pattern.
    sector = db.Column(db.String(256), nullable=True)
    subsector = db.Column(db.String(256), nullable=True)
    country = db.Column(db.String(128), nullable=True)
    scenario = db.Column(db.String(128), nullable=True)
```

Replace the `__table_args__` block (lines 114-120) with:

```python
    __table_args__ = (
        db.Index(
            "ix_forecast_run_results_run_segment",
            "forecast_run_id",
            "segment_key",
        ),
        db.Index("ix_frr_run_sector", "forecast_run_id", "sector"),
        db.Index("ix_frr_run_subsector", "forecast_run_id", "subsector"),
        db.Index("ix_frr_run_country", "forecast_run_id", "country"),
        db.Index("ix_frr_run_scenario", "forecast_run_id", "scenario"),
    )
```

- [ ] **Step 2: Confirm the current migration head before setting `down_revision`**

Run: `cd services/server && flask db heads`
Expected: a single head. If it prints `b1c3d5e7f9a1`, use it as `down_revision` below. If it prints a different/newer revision (e.g. an earlier-executed plan migration or the socketio-removal migration on this branch), set `down_revision` to whatever `flask db heads` reports instead. If it prints **two** heads, stop and resolve the branch first (`flask db merge`) — do not chain onto an ambiguous head.

- [ ] **Step 3: Write the migration (schema + chunked Python backfill)**

Create `services/server/migrations/versions/c3d5e7f9a1b3_add_forecast_facet_columns.py` (set `down_revision` to the head confirmed in Step 2):

```python
"""add denormalised facet columns to forecast_run_results

Revision ID: c3d5e7f9a1b3
Revises: b1c3d5e7f9a1
Create Date: 2026-07-11

Promotes sector/subsector/country/scenario out of meta_json into indexed
columns so filter-dropdown distinct queries are index scans, not full-run
pandas loads. Backfills existing rows from meta_json in id-ranged chunks
(dialect-agnostic Python, works on both SQLite tests and MSSQL prod).
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "c3d5e7f9a1b3"
down_revision = "b1c3d5e7f9a1"
branch_labels = None
depends_on = None

_COLS = ("sector", "subsector", "country", "scenario")
_INDEXES = {
    "sector": "ix_frr_run_sector",
    "subsector": "ix_frr_run_subsector",
    "country": "ix_frr_run_country",
    "scenario": "ix_frr_run_scenario",
}
_LEN = {"sector": 256, "subsector": 256, "country": 128, "scenario": 128}
_CHUNK = 20_000


def upgrade():
    for col in _COLS:
        op.add_column(
            "forecast_run_results",
            sa.Column(col, sa.String(_LEN[col]), nullable=True),
        )

    # Backfill from meta_json in id-ranged chunks.
    bind = op.get_bind()
    t = sa.table(
        "forecast_run_results",
        sa.column("id", sa.Integer),
        sa.column("meta_json", sa.Text),
        *[sa.column(c, sa.String) for c in _COLS],
    )
    max_id = bind.execute(sa.text("SELECT COALESCE(MAX(id), 0) FROM forecast_run_results")).scalar()
    lo = 0
    while lo < max_id:
        hi = lo + _CHUNK
        rows = bind.execute(
            sa.select(t.c.id, t.c.meta_json).where(sa.and_(t.c.id > lo, t.c.id <= hi))
        ).fetchall()
        for row in rows:
            if not row.meta_json:
                continue
            try:
                meta = json.loads(row.meta_json)
            except (TypeError, ValueError):
                continue
            values = {c: meta.get(c) for c in _COLS if meta.get(c) is not None}
            if not values:
                continue
            bind.execute(
                sa.update(t).where(t.c.id == row.id).values(**values)
            )
        lo = hi

    for col, name in _INDEXES.items():
        op.create_index(name, "forecast_run_results", ["forecast_run_id", col])


def downgrade():
    for name in _INDEXES.values():
        op.drop_index(name, table_name="forecast_run_results")
    for col in _COLS:
        op.drop_column("forecast_run_results", col)
```

- [ ] **Step 4: Apply the migration (SQLite in-process via tests, then MSSQL)**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py -v`
Expected: PASS — `db.create_all()` in the test fixture builds the new columns from the model, so tests exercise the new schema. Then apply to the real dev DB:

```bash
docker compose -f docker-compose.debug.yml up -d mssql
cd services/server && flask db upgrade
```
Expected: `Running upgrade <head> -> c3d5e7f9a1b3`, no error.

- [ ] **Step 5: Verify downgrade is clean**

Run: `cd services/server && flask db downgrade -1 && flask db upgrade`
Expected: drops then re-adds columns/indexes without error.

- [ ] **Step 6: Lint (migrations excluded from ruff format, but check imports compile)**

Run: `cd services/server && python -m py_compile migrations/versions/c3d5e7f9a1b3_add_forecast_facet_columns.py`
Expected: no output, exit 0.

- [ ] **Step 7: Commit**

```bash
git add services/server/project/db_models/forecast_models.py services/server/migrations/versions/c3d5e7f9a1b3_add_forecast_facet_columns.py
git commit -m "feat(forecast): add indexed sector/subsector/country/scenario columns"
```

---

### Task 7: Populate promoted columns on the write path

**Files:**
- Modify: `services/server/project/services/forecast_runs.py` (add `PROMOTED_DIMENSIONS`, `promoted_dims_from_meta`)
- Modify: `services/server/project/workers/forecast.py:89-100` and `:344-359`
- Test: `services/server/tests/test_forecast_distinct.py`

**Interfaces:**
- Produces: `forecast_run_service.PROMOTED_DIMENSIONS: tuple[str, ...]` = `("sector", "subsector", "country", "scenario", "segment_key")`; `forecast_run_service.promoted_dims_from_meta(meta: dict) -> dict` returning only the promoted keys present.

- [ ] **Step 1: Write the failing test**

Append to `services/server/tests/test_forecast_distinct.py`:

```python
def test_promoted_dims_from_meta_extracts_known_keys():
    from project.services.forecast_runs import promoted_dims_from_meta

    meta = {"sector": "Tech", "scenario": "Adverse", "irrelevant": "x"}
    assert promoted_dims_from_meta(meta) == {"sector": "Tech", "scenario": "Adverse"}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py -k promoted_dims -v`
Expected: FAIL — `ImportError: cannot import name 'promoted_dims_from_meta'`.

- [ ] **Step 3: Add the helper in `services/server/project/services/forecast_runs.py`**

Near the top (after imports):

```python
# meta_json keys promoted to indexed columns on forecast_run_results. segment_key
# was promoted earlier; the rest are added by migration c3d5e7f9a1b3.
PROMOTED_DIMENSIONS = ("sector", "subsector", "country", "scenario", "segment_key")


def promoted_dims_from_meta(meta: dict) -> dict:
    """Subset of a meta row limited to the promoted dimension columns present."""
    return {k: meta[k] for k in PROMOTED_DIMENSIONS if meta.get(k) is not None}
```

- [ ] **Step 4: Populate the columns in the full-run insert path**

In `services/server/project/workers/forecast.py`, in `_forecast_result_mappings` (lines 89-100), change the returned mapping so each row also carries the promoted columns. Replace the mapping dict:

```python
    return [
        {
            "forecast_run_id": fr_id,
            "date": str(dates_list[i]) if dates_list[i] is not None else None,
            "predicted": predicted_list[i],
            "meta_json": json.dumps({k: meta_dict[k][i] for k in other_keys})
            if other_keys
            else None,
            "segment_key": segment_key,
        }
        for i in range(len(predicted_list))
    ]
```

with:

```python
    from project.services.forecast_runs import promoted_dims_from_meta

    rows = []
    for i in range(len(predicted_list)):
        row_meta = {k: meta_dict[k][i] for k in other_keys}
        rows.append(
            {
                "forecast_run_id": fr_id,
                "date": str(dates_list[i]) if dates_list[i] is not None else None,
                "predicted": predicted_list[i],
                "meta_json": json.dumps(row_meta) if other_keys else None,
                "segment_key": segment_key,
                **{
                    k: v
                    for k, v in promoted_dims_from_meta(row_meta).items()
                    if k != "segment_key"  # segment_key set explicitly above
                },
            }
        )
    return rows
```

- [ ] **Step 5: Populate the columns in the main run path**

In the same file, the second insert site (lines 344-359, the `result_rows = [...]` in the `with app_session()` block). Replace that list comprehension with the equivalent explicit loop:

```python
                from project.services.forecast_runs import promoted_dims_from_meta

                result_rows = []
                for i in range(len(predicted_list)):
                    row_meta = {k: meta_dict[k][i] for k in other_keys}
                    result_rows.append(
                        {
                            "forecast_run_id": r.id,
                            "date": str(dates_list[i]) if dates_list[i] is not None else None,
                            "predicted": predicted_list[i],
                            "meta_json": json.dumps(row_meta) if other_keys else None,
                            "segment_key": seg_key_col[i] if seg_key_col else None,
                            **{
                                k: v
                                for k, v in promoted_dims_from_meta(row_meta).items()
                                if k != "segment_key"
                            },
                        }
                    )
```

- [ ] **Step 6: Run tests**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py tests/test_segment_recompute.py tests/test_e2e_pipeline.py -v`
Expected: PASS. (`test_e2e_pipeline` exercises the real forecast write path if present; if it skips without infra, that's acceptable — note it.)

- [ ] **Step 7: Lint**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add services/server/project/services/forecast_runs.py services/server/project/workers/forecast.py services/server/tests/test_forecast_distinct.py
git commit -m "feat(forecast): populate promoted dimension columns on write"
```

---

### Task 8: Answer promoted columns via indexed SQL DISTINCT

**Files:**
- Modify: `services/server/project/services/forecast_runs.py` (`distinct_for_column`)
- Test: `services/server/tests/test_forecast_distinct.py`

**Interfaces:**
- Consumes: `PROMOTED_DIMENSIONS` (Task 7), the new indexed columns (Task 6).
- Produces: `distinct_for_column` answers promoted columns with `query(col).filter(...).distinct().limit(31)`; non-promoted columns fall through to the facet cache (Task 3).

- [ ] **Step 1: Write the failing test (SQL path used for promoted, facet path for others)**

Append to `services/server/tests/test_forecast_distinct.py`:

```python
def test_promoted_column_uses_sql_not_df(app, monkeypatch):
    with app.app_context():
        fr = _seed_run()
        # If the SQL path is taken, results_df must NOT be called for a promoted col.
        monkeypatch.setattr(
            svc, "results_df", lambda *_a, **_k: pytest.fail("results_df called for promoted col")
        )
        out = svc.distinct_for_column(fr, "sector")
        assert out["values"] == ["Energy", "Financials", "Tech"]
        assert out["truncated"] is False


def test_promoted_column_truncation_flag(app):
    with app.app_context():
        fr = ForecastRun(run_id="trunc-run", status="success")
        db.session.add(fr)
        db.session.flush()
        rows = [
            {
                "forecast_run_id": fr.id,
                "date": "2030-01-01",
                "predicted": 1.0,
                "sector": f"S{i:03d}",
                "meta_json": json.dumps({"sector": f"S{i:03d}"}),
            }
            for i in range(40)  # > DISTINCT_VALUES_LIMIT (30)
        ]
        db.session.bulk_insert_mappings(ForecastRunResult, rows)
        db.session.commit()
        out = svc.distinct_for_column(fr, "sector")
        assert out["truncated"] is True
        assert len(out["values"]) == 30
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py -k "promoted_column" -v`
Expected: FAIL — current `distinct_for_column` goes through `results_df` (the monkeypatch fails the test).

- [ ] **Step 3: Add the SQL branch to `distinct_for_column`**

In `services/server/project/services/forecast_runs.py`, add the import for the limit constant and model:

```python
from project.core.table_query import DISTINCT_VALUES_LIMIT
from project.db_models.forecast_models import ForecastRunResult
```

(Merge with existing imports; `ForecastRunResult` is likely already imported.) Replace `distinct_for_column` (from Task 3) with:

```python
def _distinct_promoted(fr: ForecastRun, column: str) -> dict:
    """Indexed SELECT DISTINCT over a promoted dimension column. O(distinct
    values) via the (forecast_run_id, column) composite index — no full-run
    scan, no JSON parse."""
    col = getattr(ForecastRunResult, column)
    rows = (
        db.session.query(col)
        .filter(ForecastRunResult.forecast_run_id == fr.id, col.isnot(None))
        .distinct()
        .limit(DISTINCT_VALUES_LIMIT + 1)
        .all()
    )
    values = sorted(str(r[0]) for r in rows)
    truncated = len(values) > DISTINCT_VALUES_LIMIT
    return {"values": values[:DISTINCT_VALUES_LIMIT], "truncated": truncated}


def distinct_for_column(fr: ForecastRun, column: str) -> dict:
    """Distinct values for one result column, for a filter dropdown.

    Promoted low-cardinality dimensions are answered by an indexed SQL DISTINCT;
    every other column falls back to the per-run facet cache (one df scan cold,
    O(1) warm).
    """
    if column in PROMOTED_DIMENSIONS:
        return _distinct_promoted(fr, column)
    return _run_facets(fr).get(column, {"values": [], "truncated": False})
```

- [ ] **Step 4: Run the full distinct suite**

Run: `cd services/server && python -m pytest tests/test_forecast_distinct.py -v`
Expected: PASS (all). The `test_facets_cached_after_first_call` test still holds because it probes `sector` and `scenario` — both promoted — wait: that test asserts a df load count. **Update that test** so it probes only *non-promoted* columns (e.g. `date` twice), since promoted columns no longer hit `results_df`:

Change `test_facets_cached_after_first_call` and `test_inprogress_run_not_cached` to use a non-promoted column:

```python
        svc.distinct_for_column(fr, "date")
        svc.distinct_for_column(fr, "date")
```

and keep the `calls["n"] == 1` / `== 2` assertions respectively. Re-run to confirm PASS.

- [ ] **Step 5: Lint**

Run: `cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add services/server/project/services/forecast_runs.py services/server/tests/test_forecast_distinct.py
git commit -m "perf(forecast): answer promoted dropdowns via indexed SQL DISTINCT"
```

---

### Task 9: Stop the frontend probing numeric columns

**Files:**
- Modify: `services/client/src/views/jobs/parts/resultColumns.js:43-53`
- Test: `services/client/src/views/jobs/parts/__tests__/resultColumns.spec.js`

**Interfaces:**
- Produces: `columnsFromNames` marks numeric fields `filterable: false` (they always fell back to a text filter after a wasted probe request).

- [ ] **Step 1: Write the failing Vitest spec**

Create `services/client/src/views/jobs/parts/__tests__/resultColumns.spec.js`:

```javascript
import { describe, it, expect } from 'vitest'
import { columnsFromNames } from '../resultColumns.js'

describe('columnsFromNames', () => {
  it('marks numeric columns non-filterable so they do not fire distinct probes', () => {
    const cols = columnsFromNames(['sector', 'predicted', 'residual', 'actual'])
    const byField = Object.fromEntries(cols.map((c) => [c.field, c]))
    expect(byField.predicted.filterable).toBe(false)
    expect(byField.residual.filterable).toBe(false)
    expect(byField.actual.filterable).toBe(false)
    // categorical dimensions stay filterable (undefined ⇒ default true)
    expect(byField.sector.filterable).toBeUndefined()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/client && npx vitest run src/views/jobs/parts/__tests__/resultColumns.spec.js`
Expected: FAIL — `predicted.filterable` is `undefined`, not `false`.

- [ ] **Step 3: Mark numeric columns non-filterable**

In `services/client/src/views/jobs/parts/resultColumns.js`, in `columnsFromNames` (lines 45-53), update the numeric branch:

```javascript
    if (NUMERIC_FIELDS.has(f)) {
      return { field: f, header: f.toUpperCase(), width: '128px', align: 'right', mono: true, filterable: false, formatter: (v) => (v != null ? Number(v).toFixed(4) : '—') }
    }
```

Also update the fixed `forecastResultColumns` `predicted` entry (line 9) and `analysisResultColumns` numeric entries (`pd`, `lgd`, `ecl` — lines 19-21) to include `filterable: false` so those tables stop probing numerics too. Example for `predicted` (line 9):

```javascript
  { field: 'predicted', header: 'Predicted', width: '128px', align: 'right', mono: true, filterable: false, formatter: (v) => (v != null ? v.toFixed(4) : '—') }
```

Apply the same `filterable: false` addition to `pd`, `lgd`, `ecl`.

- [ ] **Step 4: Run the spec**

Run: `cd services/client && npx vitest run src/views/jobs/parts/__tests__/resultColumns.spec.js`
Expected: PASS.

- [ ] **Step 5: Full frontend test + build sanity**

Run: `cd services/client && npx vitest run && npm run build`
Expected: tests PASS, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add services/client/src/views/jobs/parts/resultColumns.js services/client/src/views/jobs/parts/__tests__/resultColumns.spec.js
git commit -m "perf(forecast): stop firing distinct probes for numeric columns"
```

---

### Task 10: Measure Option 2 (after) and compare

**Files:** Modify `services/server/benchmarks/BASELINE.md` → add an Option-2 section.

- [ ] **Step 1: Re-run the benchmark against MSSQL (authoritative for index behavior)**

```bash
docker compose -f docker-compose.debug.yml up -d mssql
cd services/server && flask db upgrade
cd services/server && CONFIG_NAME=dev python -m benchmarks.bench_forecast_distinct --rows 2000000 --label option2-mssql
```
Expected: promoted columns (`sector/subsector/country/scenario/segment_key`) show **near-constant cold ms independent of rows** (index scan of ≤31 values); only `date` (non-promoted) still pays the facet df scan cold. Compare `PAGE TOTAL` cold vs the `baseline-mssql` and `option1-mssql` numbers.

- [ ] **Step 2: Optional — also confirm on SQLite for a quick relative check**

Run: `cd services/server && python -m benchmarks.bench_forecast_distinct --rows 200000 --label option2-sqlite`
Expected: promoted-column times drop sharply vs baseline even without a production index planner.

- [ ] **Step 3: Append final comparison to `BASELINE.md`**

```markdown
## Option 2 — promoted indexed columns + SQL DISTINCT

| DB     | rows      | cold page ms | warm page ms | cold speedup vs baseline |
|--------|-----------|--------------|--------------|--------------------------|
| mssql  | 2,000,000 | <fill>       | <fill>       | <baseline_cold/option2_cold>x |
| sqlite | 200,000   | <fill>       | <fill>       | <fill>x |

Per-column cold ms (mssql, 2M rows):
| column      | baseline | option1 | option2 |
|-------------|----------|---------|---------|
| sector      | <fill>   | <fill>  | <fill>  |
| subsector   | <fill>   | <fill>  | <fill>  |
| country     | <fill>   | <fill>  | <fill>  |
| scenario    | <fill>   | <fill>  | <fill>  |
| segment_key | <fill>   | <fill>  | <fill>  |
| date        | <fill>   | <fill>  | <fill>  |

Takeaway: promoted columns are O(distinct) index scans — flat as rows grow —
so cold page load no longer scales with N. Option 1's cache remains as the
fast path for the one remaining df-backed column (date) and for warm loads.
```

Fill from Steps 1-2 and the earlier baseline/option1 numbers.

- [ ] **Step 4: Commit**

```bash
git add services/server/benchmarks/BASELINE.md
git commit -m "test(forecast): record Option 2 (indexed SQL) benchmark comparison"
```

---

## Out of Scope (explicit follow-ups)

- **`get_results` pagination pushdown.** [get_results](../../../services/server/project/services/forecast_runs.py) has the *same* `results_df` full-load-into-pandas flaw for its filter/sort/paginate path. Pushing `WHERE`/`ORDER BY`/`LIMIT/OFFSET` into SQL over the now-promoted columns is the natural Phase 3 and the real long-term payoff, but it changes filter/sort semantics (numeric vs string ordering, `contains` on text columns) and needs its own plan + tests. Not included here.
- **Normalizing dimensions into `sector(sector_id, sector_name)` reference tables.** Worth it for FK integrity/storage, but per-run scoping already bounds the distinct, so it's the smallest performance lever. Separate plan if desired.
- **Backfilling numeric filter pushdown / removing `meta_json`.** `meta_json` stays as the source of truth for arbitrary passthrough columns; promoted columns are a denormalized read-optimization, not a replacement.

---

## Rollout / Safety Notes

- Options 1 and 2 are independent and additive; Option 1 alone is shippable and low-risk (no migration). If Option 2 is deferred, the facet cache still covers every column.
- The migration is additive (nullable columns + indexes) and idempotent-friendly; downgrade drops cleanly. Backfill is chunked to avoid a single long transaction on large tables.
- Redis is the cache backend in dev/prod; `invalidate_facets` uses `cache.delete`, which is process-safe there. In multi-worker prod, a stale facet set can only appear between a segment re-score commit and the `invalidate_facets` call in the same task — both run in the worker, so the window is closed.
```
