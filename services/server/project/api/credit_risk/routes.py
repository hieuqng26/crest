import json
import uuid
from datetime import datetime, timezone

import pandas as pd
from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from project import cache
from project.api.auth.decorators import require_perm
from project.core import table_query
from project.db_models.calibration_models import Dataset
from project.db_models.credit_models import (
    CreditRiskForecastInput,
    CreditRiskResult,
    CreditRiskRun,
    CreditRiskRunLog,
    PdRating,
)
from project.db_models.forecast_models import ForecastRun

from . import credit_risk


# ── helpers ───────────────────────────────────────────────────────────────────


def _load_metrics(run_id: str) -> dict | None:
    from project.db_models.calibration_models import CalibrationRun

    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run or run.status != "success":
        return None
    return json.loads(run.val_metrics_json or "{}")


def _pd_rating_df(curve: str = "moodys") -> pd.DataFrame:
    rows = PdRating.query.filter_by(curve_name=curve).order_by(PdRating.category).all()
    return pd.DataFrame(
        [{"Category": r.category, "Rating": r.rating, "PD": r.pd} for r in rows]
    )


# ── v2 endpoints ──────────────────────────────────────────────────────────────


@credit_risk.get("/pd-ratings")
@require_perm("credit_risk:read")
def get_pd_ratings():
    curve = request.args.get("curve", "moodys")
    rows = PdRating.query.filter_by(curve_name=curve).order_by(PdRating.category).all()
    return jsonify([r.to_dict() for r in rows]), 200


@credit_risk.get("/clients")
@require_perm("credit_risk:read")
def get_clients():
    from project.db_models.calibration_models import Dataset
    from project import DATA_STORE
    import os

    mock = request.args.get("mock", "false").lower() == "true"
    if mock:
        from project.core.credit_risk.mock_credit import mock_credit_data

        df = mock_credit_data()
        return jsonify(df["client_id"].tolist()), 200

    dataset_id = request.args.get("dataset_id")
    if not dataset_id:
        return jsonify({"error": "dataset_id or mock=true is required"}), 400

    dataset = Dataset.query.get(int(dataset_id))
    if not dataset or not dataset.file_path:
        return jsonify({"error": "Dataset not found"}), 404

    path = (
        dataset.file_path
        if os.path.isabs(dataset.file_path)
        else os.path.join(DATA_STORE, dataset.file_path)
    )
    try:
        df = _read_dataset(path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if "client_id" not in df.columns:
        return jsonify({"error": "Dataset has no client_id column"}), 400

    return jsonify(sorted(df["client_id"].unique().tolist())), 200


@credit_risk.post("/kmv")
@require_perm("credit_risk:read")
def compute_kmv():
    from project.core.credit_risk.kmv import run_kmv

    body = request.get_json(silent=True) or {}
    mock = body.get("mock", False)
    client_id = body.get("client_id")
    scenarios = body.get("scenarios")

    if not client_id:
        return jsonify({"error": "client_id is required"}), 400

    try:
        pd_df = _pd_rating_df(body.get("curve", "moodys"))
        if pd_df.empty:
            return jsonify(
                {"error": "No PD ratings found. Run flask db upgrade first."}
            ), 500

        if mock:
            from project.core.credit_risk.mock_credit import (
                mock_credit_data,
                mock_kmv_forecast,
            )

            clients_df = mock_credit_data()
            client_row = clients_df[clients_df["client_id"] == client_id]
            if client_row.empty:
                return jsonify(
                    {"error": f"Client '{client_id}' not found in mock data"}
                ), 404
            c = client_row.iloc[0]
            com_info = {
                "E0": float(c["market_cap"]),
                "volE": float(c["vol_equity"]),
                "r": float(c["risk_free_rate"]),
                "rating": str(c["rating"]),
            }
            forecast = mock_kmv_forecast(client_id, scenarios=scenarios)
        else:
            dataset_id = body.get("dataset_id")
            if not dataset_id:
                return jsonify({"error": "dataset_id or mock=true is required"}), 400
            com_info, forecast = _load_client_data(int(dataset_id), client_id)

        result_df = run_kmv(com_info, forecast, pd_df)
        records = result_df.where(pd.notnull(result_df), None).to_dict(orient="records")
        return jsonify({"client_id": client_id, "rows": records}), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500


@credit_risk.post("/ecl")
@require_perm("credit_risk:read")
def compute_ecl_v2():
    from project.core.credit_risk.ecl import compute_ecl
    from project.core.credit_risk.kmv import run_kmv

    body = request.get_json(silent=True) or {}

    # Accept either pre-computed KMV rows or re-run from scratch
    kmv_rows = body.get("kmv_result")
    exposure = body.get("exposure")
    discount_rate = body.get("discount_rate", 0.05)
    lifetime_horizon = int(body.get("lifetime_horizon", 5))

    if exposure is None:
        return jsonify({"error": "exposure is required"}), 400

    try:
        if kmv_rows:
            kmv_df = pd.DataFrame(kmv_rows)
        else:
            # Re-run KMV inline
            mock = body.get("mock", False)
            client_id = body.get("client_id")
            if not client_id:
                return jsonify({"error": "client_id or kmv_result is required"}), 400

            pd_df = _pd_rating_df(body.get("curve", "moodys"))
            if mock:
                from project.core.credit_risk.mock_credit import (
                    mock_credit_data,
                    mock_kmv_forecast,
                )

                clients_df = mock_credit_data()
                client_row = clients_df[clients_df["client_id"] == client_id]
                if client_row.empty:
                    return jsonify(
                        {"error": f"Client '{client_id}' not found in mock data"}
                    ), 404
                c = client_row.iloc[0]
                com_info = {
                    "E0": float(c["market_cap"]),
                    "volE": float(c["vol_equity"]),
                    "r": float(c["risk_free_rate"]),
                    "rating": str(c["rating"]),
                }
                forecast = mock_kmv_forecast(client_id)
            else:
                dataset_id = body.get("dataset_id")
                if not dataset_id:
                    return jsonify(
                        {"error": "dataset_id or mock=true is required"}
                    ), 400
                com_info, forecast = _load_client_data(int(dataset_id), client_id)
            kmv_df = run_kmv(com_info, forecast, pd_df)

        ecl_df = compute_ecl(
            kmv_df, float(exposure), float(discount_rate), lifetime_horizon
        )
        records = ecl_df.where(pd.notnull(ecl_df), None).to_dict(orient="records")
        return jsonify({"rows": records}), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500


# ── analysis run management ───────────────────────────────────────────────────


@credit_risk.get("/runs")
@require_perm("credit_risk:read")
def list_runs():
    runs = CreditRiskRun.query.order_by(CreditRiskRun.created_at.desc()).all()
    result = []
    for r in runs:
        d = r.to_dict()
        ds = Dataset.query.get(r.dataset_id)
        d["dataset_name"] = ds.name if ds else None
        result.append(d)
    return jsonify(result), 200


@credit_risk.post("/runs")
@require_perm("credit_risk:execute")
def create_run():
    from project import app_session
    from project.workers.tasks import run_credit_analysis

    body = request.get_json(silent=True) or {}
    dataset_id = body.get("dataset_id")
    if not dataset_id:
        return jsonify({"error": "dataset_id is required"}), 400

    ds = Dataset.query.get(int(dataset_id))
    if not ds:
        return jsonify({"error": "Dataset not found"}), 404

    financial_portfolio_dataset_id = body.get("financial_portfolio_dataset_id")
    if financial_portfolio_dataset_id:
        fin_ds = Dataset.query.get(int(financial_portfolio_dataset_id))
        if not fin_ds:
            return jsonify({"error": "Financial portfolio dataset not found"}), 404
        financial_portfolio_dataset_id = int(financial_portfolio_dataset_id)

    forecast_inputs = body.get("cal_inputs") or {}
    required_keys = {"total_assets", "short_term_debts", "long_term_debts"}
    missing = required_keys - {k for k, v in forecast_inputs.items() if v}
    if missing:
        return jsonify(
            {"error": f"Missing required forecast inputs: {sorted(missing)}"}
        ), 400

    # Resolve each slot's UUID to its integer PK — validates existence and acts as
    # the FK reference that will block accidental deletion of the forecast run.
    slot_to_forecast_run: dict[str, ForecastRun] = {}
    for slot, run_uuid in forecast_inputs.items():
        fr = ForecastRun.query.filter_by(run_id=run_uuid).first()
        if not fr or fr.status != "success":
            return jsonify(
                {"error": f"Forecast run for '{slot}' not found or not successful"}
            ), 400
        slot_to_forecast_run[slot] = fr

    cr_run_id = str(uuid.uuid4())
    identity = get_jwt_identity()

    cr = CreditRiskRun(
        run_id=cr_run_id,
        dataset_id=int(dataset_id),
        financial_portfolio_dataset_id=financial_portfolio_dataset_id,
        is_active=False,
        exposure=float(body.get("exposure", 1_000_000)),
        discount_rate=float(body.get("discount_rate", 0.05)),
        lifetime_horizon=int(body.get("lifetime_horizon", 5)),
        curve=body.get("curve", "moodys"),
        status="queued",
        triggered_by=identity,
        created_at=datetime.now(timezone.utc),
    )
    with app_session() as s:
        s.add(cr)
        s.flush()
        for slot, fr in slot_to_forecast_run.items():
            s.add(
                CreditRiskForecastInput(
                    credit_risk_run_id=cr.id,
                    forecast_run_id=fr.id,
                    forecast_run_uuid=fr.run_id,
                    slot=slot,
                )
            )
        s.flush()
        cr_dict = cr.to_dict()

    run_credit_analysis.delay(cr_run_id)
    return jsonify(cr_dict), 202


@credit_risk.get("/runs/active")
@require_perm("credit_risk:read")
def get_active_run():
    cr = CreditRiskRun.query.filter_by(is_active=True).first()
    if not cr:
        return jsonify({"error": "No active run"}), 404
    d = cr.to_dict()
    ds = Dataset.query.get(cr.dataset_id)
    d["dataset_name"] = ds.name if ds else None
    results = CreditRiskResult.query.filter_by(run_id=cr.run_id).all()
    d["client_ids"] = sorted({r.client_id for r in results})
    return jsonify(d), 200


@credit_risk.put("/runs/<cr_run_id>/active")
@require_perm("credit_risk:execute")
def set_active_run(cr_run_id: str):
    from project import app_session

    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404
    if cr.status != "success":
        return jsonify({"error": "Only completed runs can be set as active"}), 400

    with app_session() as s:
        for row in CreditRiskRun.query.filter_by(is_active=True).all():
            row.is_active = False
            s.add(row)
        r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
        r.is_active = True
        s.add(r)

    return jsonify({"ok": True}), 200


@credit_risk.post("/runs/<cr_run_id>/rerun")
@require_perm("credit_risk:execute")
def rerun_run(cr_run_id: str):
    from project import app_session
    from project.workers.tasks import run_credit_analysis

    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404

    with app_session() as s:
        CreditRiskResult.query.filter_by(run_id=cr_run_id).delete()
        r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
        r.status = "queued"
        r.progress = 0
        r.started_at = None
        r.finished_at = None
        r.error_message = None
        s.add(r)

    run_credit_analysis.delay(cr_run_id)
    return jsonify({"ok": True}), 202


@credit_risk.post("/runs/<cr_run_id>/cancel")
@require_perm("credit_risk:execute")
def cancel_run(cr_run_id: str):
    from project import app_session

    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404
    if cr.status not in ("queued", "running"):
        return jsonify({"error": f"Cannot cancel a run with status '{cr.status}'"}), 409

    with app_session() as s:
        r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
        r.status = "failed"
        r.finished_at = datetime.now(timezone.utc)
        r.error_message = "Cancelled by user"
        s.add(r)
        s.flush()
        result = r.to_dict()

    return jsonify(result), 200


def _client_stage(
    latest_kmv: dict | None,
    first_kmv: dict | None,
    rating_to_category: dict[str, int],
    n_categories: int,
) -> int | None:
    """
    Simplified IFRS 9 staging proxy (SICR = significant increase in credit risk):
      - Stage 3 (credit-impaired): rating falls in the worst 2 categories of the curve.
      - Stage 2 (SICR): rating has downgraded by >=2 categories vs the first forecast year.
      - Stage 1 (performing): otherwise.
    This compares rating *category* (ordinal rank on the PD curve), not raw PD, since
    categories are already ordered worst-to-best consistently across curves. It is a
    proxy, not a full origination-vs-current-date IFRS 9 assessment — see
    .claude/docs for the caveat before relying on it for regulatory reporting.
    """
    if not latest_kmv or not n_categories:
        return None
    cur_cat = rating_to_category.get(latest_kmv.get("Rating"))
    if cur_cat is None:
        return None
    if cur_cat >= n_categories - 1:
        return 3
    base_cat = rating_to_category.get((first_kmv or {}).get("Rating"))
    if base_cat is not None and cur_cat - base_cat >= 2:
        return 2
    return 1


def _run_results_df(cr: CreditRiskRun) -> pd.DataFrame:
    cache_key = f"cr_run_results:{cr.run_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    results = (
        CreditRiskResult.query.filter_by(run_id=cr.run_id)
        .order_by(CreditRiskResult.id)
        .all()
    )

    pd_rating_df = _pd_rating_df(cr.curve)
    rating_to_category = dict(zip(pd_rating_df["Rating"], pd_rating_df["Category"]))
    n_categories = len(rating_to_category)

    rows = []
    for r in results:
        kmv_rows = json.loads(r.kmv_json or "[]")
        ecl_rows = json.loads(r.ecl_json or "[]")

        baseline_kmv = [
            k for k in kmv_rows if str(k.get("SCENARIO", "")).lower() == "baseline"
        ] or kmv_rows
        baseline_ecl = [
            e for e in ecl_rows if str(e.get("SCENARIO", "")).lower() == "baseline"
        ] or ecl_rows
        first_kmv = min(baseline_kmv, key=lambda k: k.get("YEAR", 0), default=None)

        # compute_ecl()'s final forecast year has no forward year to project into, so
        # ECL_12M/ECL_Lifetime are structurally zero there (see ecl.py's trailing
        # np.append(..., 0.0)) — and since ECL_12M is a one-year-forward-shifted
        # calculation, that zero LGD cascades into the second-to-last year too. Pick
        # the most recent year with a genuinely computed ECL so the summary isn't
        # built from a degenerate boundary row; fall back to the raw latest year if
        # every row is zero (e.g. a single-year forecast).
        non_boundary_ecl = [
            e for e in baseline_ecl if e.get("ECL_12M") or e.get("ECL_Lifetime")
        ]
        ecl_match = max(
            non_boundary_ecl or baseline_ecl,
            key=lambda e: e.get("YEAR", 0),
            default=None,
        )

        # Read PD/LGD/Rating from the same (year, scenario) as the ECL figure so the
        # whole summary row describes one consistent point in time.
        latest_kmv = None
        if ecl_match:
            latest_kmv = next(
                (k for k in baseline_kmv if k.get("YEAR") == ecl_match.get("YEAR")),
                None,
            )
        if latest_kmv is None:
            latest_kmv = max(baseline_kmv, key=lambda k: k.get("YEAR", 0), default=None)

        rows.append(
            {
                "client_id": r.client_id,
                "stage": _client_stage(
                    latest_kmv, first_kmv, rating_to_category, n_categories
                ),
                "pd": latest_kmv.get("PD") if latest_kmv else None,
                "lgd": latest_kmv.get("LGD") if latest_kmv else None,
                "ecl": ecl_match.get("ECL_Lifetime") if ecl_match else None,
                "scenario": (ecl_match or latest_kmv or {}).get("SCENARIO"),
                "year": (ecl_match or latest_kmv or {}).get("YEAR"),
            }
        )

    df = pd.DataFrame.from_records(rows)
    cache.set(cache_key, df, timeout=60)
    return df


@credit_risk.get("/runs/<cr_run_id>/results")
@require_perm("credit_risk:read")
def get_run_results(cr_run_id: str):
    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404

    df = _run_results_df(cr)
    page, total = table_query.query_page(
        df,
        page=int(request.args.get("page", 0)),
        page_size=int(request.args.get("page_size", 50)),
        sort_column=request.args.get("sort_column"),
        sort_order=request.args.get("sort_order"),
        filters=table_query.parse_filters(request.args.get("filters")),
    )
    rows = page.where(pd.notnull(page), None).to_dict(orient="records")
    return jsonify({"rows": rows, "total": total}), 200


@credit_risk.get("/runs/<cr_run_id>/results/distinct")
@require_perm("credit_risk:read")
def get_run_results_distinct(cr_run_id: str):
    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404
    column = request.args.get("column", "")
    if not column:
        return jsonify({"values": [], "truncated": False}), 200

    df = _run_results_df(cr)
    return jsonify(table_query.distinct_values(df, column)), 200


@credit_risk.delete("/runs/<cr_run_id>")
@require_perm("credit_risk:write")
def delete_run(cr_run_id: str):
    from project import app_session

    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404

    with app_session() as s:
        CreditRiskRunLog.query.filter_by(run_id=cr_run_id).delete()
        r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
        s.delete(r)

    return jsonify({"ok": True}), 200


@credit_risk.get("/runs/<cr_run_id>")
@require_perm("credit_risk:read")
def get_run(cr_run_id: str):
    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404
    d = cr.to_dict()
    ds = Dataset.query.get(cr.dataset_id)
    d["dataset_name"] = ds.name if ds else None
    results = CreditRiskResult.query.filter_by(run_id=cr_run_id).all()
    d["client_ids"] = sorted({r.client_id for r in results})
    return jsonify(d), 200


@credit_risk.get("/runs/<cr_run_id>/logs")
@require_perm("credit_risk:read")
def get_run_logs(cr_run_id: str):
    logs = (
        CreditRiskRunLog.query.filter_by(run_id=cr_run_id)
        .order_by(CreditRiskRunLog.id)
        .all()
    )
    return jsonify([log.to_dict() for log in logs]), 200


@credit_risk.get("/runs/<cr_run_id>/client/<client_id>")
@require_perm("credit_risk:read")
def get_client_result(cr_run_id: str, client_id: str):
    result = CreditRiskResult.query.filter_by(
        run_id=cr_run_id, client_id=client_id
    ).first()
    if not result:
        return jsonify({"error": "Result not found"}), 404
    return jsonify(
        {
            "kmv": json.loads(result.kmv_json or "[]"),
            "ecl": json.loads(result.ecl_json or "[]"),
        }
    ), 200


# ── v1 dummies (retained) ─────────────────────────────────────────────────────


@credit_risk.post("/ecl/v1")
@require_perm("credit_risk:read")
def compute_ecl_v1():
    body = request.get_json(silent=True) or {}
    portfolio = body.get("portfolio", [])
    if not portfolio:
        return jsonify({"error": "portfolio is required"}), 400

    results = []
    total_ecl = 0.0
    stage_ecl: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0}

    for seg in portfolio:
        ead = float(seg.get("ead", 0))
        pd_ = float(seg.get("pd", 0))
        lgd = float(seg.get("lgd", 0))
        stage = int(seg.get("stage", 1))
        ecl = ead * pd_ * lgd
        total_ecl += ecl
        stage_ecl[stage] = stage_ecl.get(stage, 0.0) + ecl
        results.append({**seg, "ecl": round(ecl, 2)})

    return jsonify(
        {
            "total_ecl": round(total_ecl, 2),
            "stage_breakdown": [
                {"stage": k, "ecl": round(v, 2)} for k, v in stage_ecl.items()
            ],
            "segments": results,
        }
    ), 200


@credit_risk.post("/pd-lgd/v1")
@require_perm("credit_risk:read")
def compute_pd_lgd_v1():
    body = request.get_json(silent=True) or {}
    run_ids = body.get("run_ids", [])
    horizons = body.get("horizons", [1, 2, 3, 5, 7, 10])

    curves = []
    for run_id in run_ids:
        metrics = _load_metrics(run_id)
        if not metrics:
            continue
        from project.db_models.calibration_models import CalibrationRun

        run = CalibrationRun.query.filter_by(run_id=run_id).first()
        base_pd = max(0.001, metrics.get("auc_roc", 0.5) - 0.5)
        pd_curve = [round(min(1.0, base_pd * h**0.7), 4) for h in horizons]
        lgd_curve = [round(min(1.0, 0.40 + 0.02 * h), 4) for h in horizons]
        curves.append(
            {
                "run_id": run_id,
                "config_name": run.model_config.name
                if run and run.model_config
                else run_id,
                "horizons": horizons,
                "pd": pd_curve,
                "lgd": lgd_curve,
            }
        )

    return jsonify({"curves": curves}), 200


# ── private helpers ───────────────────────────────────────────────────────────


def _read_dataset(path: str) -> pd.DataFrame:
    if path.endswith(".parquet"):
        return pd.read_parquet(path)
    if path.endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    return pd.read_csv(path)


def _load_client_data(dataset_id: int, client_id: str):
    from project.db_models.calibration_models import Dataset
    from project import DATA_STORE
    import os

    dataset = Dataset.query.get(dataset_id)
    if not dataset or not dataset.file_path:
        raise ValueError(f"Dataset {dataset_id} not found")

    path = (
        dataset.file_path
        if os.path.isabs(dataset.file_path)
        else os.path.join(DATA_STORE, dataset.file_path)
    )
    df = _read_dataset(path)
    client_df = df[df["client_id"] == client_id]
    if client_df.empty:
        raise ValueError(f"Client '{client_id}' not found in dataset {dataset_id}")

    required = {"market_cap", "vol_equity", "risk_free_rate", "rating"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Dataset missing required columns: {missing}")

    row = client_df.iloc[0]
    com_info = {
        "E0": float(row["market_cap"]),
        "volE": float(row["vol_equity"]),
        "r": float(row["risk_free_rate"]),
        "rating": str(row["rating"]),
    }

    required_forecast = {"YEAR", "Total_Asset", "CL", "NonCL"}
    missing_f = required_forecast - set(df.columns)
    if missing_f:
        raise ValueError(f"Dataset missing forecast columns: {missing_f}")

    forecast_cols = ["YEAR", "Total_Asset", "CL", "NonCL"]
    if "SCENARIO" in df.columns:
        forecast_cols.append("SCENARIO")
    forecast = client_df[forecast_cols].copy()
    if "SCENARIO" not in forecast.columns:
        forecast["SCENARIO"] = "Baseline"

    return com_info, forecast
