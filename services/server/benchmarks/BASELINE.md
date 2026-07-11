# Forecast distinct benchmark — baseline (df scan)

Method: `python -m benchmarks.bench_forecast_distinct`. Probed columns:
sector, subsector, country, scenario, segment_key, date (6 parallel probes on
table load, per CommonDataTable's `resolveFilterKinds`). Each number is the
median of 3 repeats; PAGE TOTAL is the sum across the 6 columns (what one page
load costs).

At baseline, `distinct_for_column` does a full `results_df` load (SELECT all of
the run's rows) + `json.loads` per row into pandas, for every column — so all
six columns cost the same and cold ≈ warm (no cache exists yet).

| DB     | rows    | cold page ms | warm page ms |
|--------|---------|--------------|--------------|
| sqlite | 200,000 | 8644.16      | 8649.51      |
| mssql  | 500,000 | deferred     | deferred     |

Per-column cold ms (sqlite, 200k rows): sector 1460.6 · subsector 1433.7 ·
country 1444.1 · scenario 1437.7 · segment_key 1440.7 · date 1427.4 — uniform,
because each is a full-run load, not a column-specific query.

## MSSQL fidelity — deferred

The authoritative production-index numbers must come from MSSQL, but the host
venv cannot load the ODBC driver (`libodbc.2.dylib` absent — the same reason
`tests/conftest.py` stubs `pyodbc`), so the host benchmark cannot connect to
the running `mst-mssql-1` container (published on :1433). Capture MSSQL numbers
by either (a) running the harness inside a container that has the msodbcsql17
driver with the worktree code mounted, or (b) `brew install unixodbc` +
msodbcsql17 on the host, then `CONFIG_NAME=dev python -m
benchmarks.bench_forecast_distinct --rows 500000 --label baseline-mssql`.
SQLite still demonstrates the dominant cost (the O(N) pandas load + JSON parse)
and the relative before/after of each option.

---

## Option 1 — per-run facet cache

Re-run at commit 2db2cd5 (facet cache + guarded invalidation in place). Same
SQLite, 200k rows. `distinct_for_column` now reads from a per-run cache computed
once (all columns in a single `results_df` scan).

| DB     | rows    | cold page ms | warm page ms | vs baseline (page) |
|--------|---------|--------------|--------------|--------------------|
| sqlite | 200,000 | 0.08         | 0.01         | ~108,000× faster   |
| mssql  | 500,000 | deferred     | deferred     | — (no host ODBC)   |

Per-column cold ms (sqlite, 200k): all ≤ 0.04 (cache hits).

**Reading these numbers honestly.** The harness times median-of-3 repeats per
column, so the single cache *miss* (the first probe of the first column, which
computes all-column facets in one df scan ≈ one baseline column ≈ 1.44s) is
amortized away by the two subsequent hits and does not show in the median. So:

- **Repeat page loads** (the common case — immutable run, ~100% hit rate): every
  dropdown is a cache hit → **8644ms → ~0ms**.
- **First page load of a run:** previously each of the 6 columns did its own
  full-run scan (6 × 1.44s ≈ 8.6s); now the first probe computes all facets in
  ONE scan (~1.44s) and the other five hit cache → **~8.6s → ~1.44s, ≈6× faster**
  even on the very first load.

The one remaining cost is that single ~1.44s cold facet computation, which still
scales with rows-in-run (O(N)). Option 2 removes that for the promoted columns.
