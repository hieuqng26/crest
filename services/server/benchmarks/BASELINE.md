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
