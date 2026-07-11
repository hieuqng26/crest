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
import sys
import time
import types
import uuid
from pathlib import Path

os.environ.setdefault("CONFIG_NAME", "testing")

# pyodbc is a native extension that requires unixodbc to be installed. On dev
# machines where the shared library is absent, mock it before any blueprint
# import triggers the top-level `import pyodbc` (mirrors tests/conftest.py;
# only the MSSQL driver path needs the real module, not this SQLite run).
if "pyodbc" not in sys.modules:
    sys.modules["pyodbc"] = types.ModuleType("pyodbc")

from project import cache, create_app, db  # noqa: E402
from project.api.users.models import User  # noqa: E402
from project.config import TestingConfig  # noqa: E402
from project.db_models.calibration_models import (  # noqa: E402
    CalibrationRun,
    Dataset,
    ModelConfig,
)
from project.db_models.forecast_models import ForecastRun, ForecastRunResult  # noqa: E402
from project.services import forecast_runs as svc  # noqa: E402

# TestingConfig hardcodes SQLALCHEMY_ECHO=True (handy for pytest debugging),
# but that logging fires inside every timed distinct_for_column() call below
# and would both swamp the console and inflate the very wall-clock numbers
# this harness measures, especially at --rows 200_000+. Echo is bound at
# engine-creation time inside create_app(), so it must be patched off on the
# config *class* beforehand (see .claude/bugs/mcp-stdio-sqlalchemy-echo.md).
TestingConfig.SQLALCHEMY_ECHO = False

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

        # ForecastRun.calibration_run_id / dataset_id are NOT NULL FKs, so build
        # the minimal parent chain (user -> dataset -> model config ->
        # calibration run) before creating the forecast run itself.
        user = User(
            email="bench@example.com",
            password="Passw0rd!",
            role="sysadmin",
            name="bench",
        )
        user.status = "active"
        db.session.add(user)
        db.session.commit()
        ds = Dataset(
            name="fc-ds",
            source="upload",
            file_path="uploads/fc.csv",
            row_count=0,
            created_by=user.email,
            status="ready",
            kind="forecast",
        )
        cfg = ModelConfig(
            name="cfg",
            family="regression",
            algorithm="ElasticNet",
            hyperparams_json="{}",
            train_split=0.8,
            created_by=user.email,
        )
        db.session.add_all([ds, cfg])
        db.session.commit()
        cal = CalibrationRun(
            run_id=f"cal-{uuid.uuid4()}",
            dataset_id=ds.id,
            model_config_id=cfg.id,
            status="success",
            triggered_by=user.email,
        )
        db.session.add(cal)
        db.session.commit()

        fr = ForecastRun(
            run_id=f"bench-{uuid.uuid4()}",
            status="success",
            calibration_run_id=cal.id,
            dataset_id=ds.id,
        )
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
            print(
                f"{col:<14}{cold['per_column_ms'][col]:>10}{warm['per_column_ms'][col]:>10}"
            )
        print(
            f"{'PAGE TOTAL':<14}{cold['page_total_ms']:>10}{warm['page_total_ms']:>10}"
        )
        print(f"\nwrote {out}")

        # Clean up so repeat runs don't accumulate rows in a persistent DB.
        ForecastRunResult.query.filter_by(forecast_run_id=fr.id).delete()
        db.session.query(ForecastRun).filter_by(id=fr.id).delete()
        db.session.commit()


if __name__ == "__main__":
    main()
