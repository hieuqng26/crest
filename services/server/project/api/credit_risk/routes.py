import json
import os
from datetime import datetime, timezone

import pandas as pd
from flask import current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.orm import selectinload

from project import DATA_STORE, app_session, cache, db
from project.api.auth.decorators import require_perm
from project.api.helpers import pagination_envelope
from project.api.utils import paginate_logs
from project.core import table_query
from project.db_models.calibration_models import Dataset
from project.db_models.credit_models import (
    CreditRiskAnalysisSeries,
    CreditRiskForecastInput,
    CreditRiskResult,
    CreditRiskRun,
    CreditRiskRunLog,
    PdRating,
)
from project.db_models.forecast_models import ForecastRun
from project.schemas.credit_risk import CreateCreditRiskRun
from project.services import credit_analysis
from project.services import credit_risk as credit_risk_service
from project.services.run_guards import ensure_not_workflow_member

from . import credit_risk


# ── helpers ───────────────────────────────────────────────────────────────────


def _reject_mock_if_disabled(requested_mock: bool):
    """Return a 400 response tuple if mock data is requested but disabled.

    Mock credit data (mock_credit.py) is a dev/test convenience gated by the
    ALLOW_MOCK_CREDIT config flag — it must never be reachable in production."""
    if requested_mock and not current_app.config.get("ALLOW_MOCK_CREDIT", False):
        return jsonify(
            {"error": "Mock credit data is disabled in this environment"}
        ), 400
    return None


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

    mock = request.args.get("mock", "false").lower() == "true"
    if (resp := _reject_mock_if_disabled(mock)) is not None:
        return resp
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
    # A read failure here is an internal error — let it reach the global
    # boundary (logged, generic 500) rather than echoing the raw error.
    df = _read_dataset(path)

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

    if (resp := _reject_mock_if_disabled(mock)) is not None:
        return resp
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
        # User-facing semantic error (bad inputs); unexpected errors fall
        # through to the global boundary (logged, generic 500 — no leak).
        return jsonify({"error": str(e)}), 422


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
            if (resp := _reject_mock_if_disabled(mock)) is not None:
                return resp
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
        # User-facing semantic error (bad inputs); unexpected errors fall
        # through to the global boundary (logged, generic 500 — no leak).
        return jsonify({"error": str(e)}), 422


# ── analysis run management ───────────────────────────────────────────────────


@credit_risk.get("/runs")
@require_perm("credit_risk:read")
def list_runs():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    runs = (
        CreditRiskRun.query.options(selectinload(CreditRiskRun.forecast_inputs_rel))
        .order_by(CreditRiskRun.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    ds_ids = {r.dataset_id for r in runs.items}
    datasets = (
        {d.id: d for d in Dataset.query.filter(Dataset.id.in_(ds_ids))}
        if ds_ids
        else {}
    )

    result = []
    for r in runs.items:
        d = r.to_dict()
        ds = datasets.get(r.dataset_id)
        d["dataset_name"] = ds.name if ds else None
        result.append(d)

    return jsonify(pagination_envelope(result, runs)), 200


@credit_risk.post("/runs")
@require_perm("credit_risk:execute")
def create_run():
    payload = CreateCreditRiskRun.model_validate(request.get_json(silent=True) or {})
    cr_dict = credit_risk_service.create_run(payload, get_jwt_identity())
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
    client_ids = (
        CreditRiskResult.query.with_entities(CreditRiskResult.client_id)
        .filter_by(run_id=cr.run_id)
        .distinct()
        .all()
    )
    d["client_ids"] = sorted(c[0] for c in client_ids)
    return jsonify(d), 200


@credit_risk.put("/runs/<cr_run_id>/active")
@require_perm("credit_risk:execute")
def set_active_run(cr_run_id: str):

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
    from project.workers.tasks import run_credit_analysis

    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404
    ensure_not_workflow_member(cr)

    with app_session() as s:
        CreditRiskResult.query.filter_by(run_id=cr_run_id).delete()
        r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
        # Drop the materialised analysis series — it'll be rebuilt when the rerun
        # completes (and would otherwise show stale numbers in the meantime).
        CreditRiskAnalysisSeries.query.filter_by(credit_risk_run_id=r.id).delete()
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
        workflow_run_id = r.workflow_run_id
        s.add(r)
        s.flush()
        result = r.to_dict()

    if workflow_run_id:
        from project.workers.tasks import advance_workflow

        advance_workflow.delay(workflow_run_id)
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
                "sector": r.sector,
                "segment_key": r.segment_key,
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
    # A run's results are immutable except via segment recompute, which explicitly
    # deletes this key (recompute_segment_downstream), so a long TTL is safe and
    # avoids rebuilding the frame from every CreditRiskResult row each minute.
    cache.set(cache_key, df, timeout=3600)
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

    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404
    ensure_not_workflow_member(cr)

    with app_session() as s:
        CreditRiskRunLog.query.filter_by(run_id=cr_run_id).delete()
        r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
        CreditRiskAnalysisSeries.query.filter_by(credit_risk_run_id=r.id).delete()
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
    client_ids = (
        CreditRiskResult.query.with_entities(CreditRiskResult.client_id)
        .filter_by(run_id=cr_run_id)
        .distinct()
        .all()
    )
    d["client_ids"] = sorted(c[0] for c in client_ids)
    if cr.workflow_run_id:
        from project.db_models.workflow_models import WorkflowRun

        wf = WorkflowRun.query.get(cr.workflow_run_id)
        d["workflow_run_uuid"] = wf.run_id if wf else None
    return jsonify(d), 200


@credit_risk.get("/runs/<cr_run_id>/logs")
@require_perm("credit_risk:read")
def get_run_logs(cr_run_id: str):
    logs = paginate_logs(
        CreditRiskRunLog.query.filter_by(run_id=cr_run_id), CreditRiskRunLog.id
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


# ── Analysis: Sector Heatmap & Financial Forecast ─────────────────────────────
#
# Both screens read from the active CreditRiskRun: its credit + financial-portfolio
# datasets (for sector/subsector/country routing, same merge the Celery task does)
# and its linked ForecastRun "slots". total_assets / short_term_debts /
# long_term_debts are the 3 slots required to run KMV at all; total_revenue and
# total_cogs are optional extra slots (added via the same New Analysis form) that
# unlock these two Analysis screens. "History" comes from the actual dataset each
# forecast run's calibration was trained on (real historical actuals), not mocked.


def _load_dataset_df(dataset) -> pd.DataFrame:
    """Download + parse a Dataset's file from MinIO — same object-key convention
    as the credit-risk analysis Celery task (`run_credit_analysis`).

    Two cache layers: request-scoped `g` (one request can reference the same
    dataset several times) and the cross-request app `cache` keyed by dataset id +
    file_path. A dataset's file is immutable per file_path (a re-upload gets a new
    path), so the cross-request entry never goes stale and only needs a TTL for
    memory hygiene. This is the fix for re-downloading + re-parsing on every
    heatmap/forecast request and every 5 s poll."""
    from flask import g

    from project.core import dataset_io

    g_key = f"_dataset_df_{dataset.id}"
    cached = getattr(g, g_key, None)
    if cached is not None:
        return cached

    xcache_key = f"cr_dataset_df:{dataset.id}:{dataset.file_path}"
    df = cache.get(xcache_key)
    if df is None:
        df = dataset_io.download_dataset_df(dataset)
        cache.set(xcache_key, df, timeout=3600)

    setattr(g, g_key, df)
    return df


def _get_analysis_run(run_id: str | None) -> "CreditRiskRun":
    from project.db_models.credit_models import CreditRiskRun

    cr = (
        CreditRiskRun.query.filter_by(run_id=run_id).first()
        if run_id
        else CreditRiskRun.query.filter_by(is_active=True).first()
    )
    if not cr:
        raise ValueError("No active credit risk run" if not run_id else "Run not found")
    if cr.status != "success":
        raise ValueError("This run has not completed successfully")
    return cr


def _slot_forecast_runs(cr) -> dict[str, ForecastRun]:

    slots = {}
    for inp in CreditRiskForecastInput.query.filter_by(credit_risk_run_id=cr.id).all():
        fr = ForecastRun.query.get(inp.forecast_run_id)
        if fr and fr.status == "success":
            slots[inp.slot] = fr
    return slots


def _analysis_portfolio_df(cr) -> pd.DataFrame:
    credit_ds = Dataset.query.get(cr.dataset_id)
    if not credit_ds or not credit_ds.file_path:
        raise ValueError("Credit dataset not found")
    portfolio_df = _load_dataset_df(credit_ds)

    if cr.financial_portfolio_dataset_id:
        fin_ds = Dataset.query.get(cr.financial_portfolio_dataset_id)
        if fin_ds and fin_ds.file_path:
            fin_df = _load_dataset_df(fin_ds)
            meta_cols = [
                c
                for c in ("client_id", "country", "sector", "subsector")
                if c in fin_df.columns
            ]
            if "client_id" in meta_cols:
                fin_meta = fin_df[meta_cols].drop_duplicates(subset=["client_id"])
                new_cols = ["client_id"] + [
                    c
                    for c in meta_cols
                    if c != "client_id" and c not in portfolio_df.columns
                ]
                portfolio_df = portfolio_df.merge(
                    fin_meta[new_cols], on="client_id", how="left"
                )
    return portfolio_df


def _historical_series(
    fr: ForecastRun, sector: str | None, client_id: str | None
) -> dict:
    """Actual historical {year: summed target value} from the dataset this forecast
    run's calibration was trained on — filtered to one client, or summed across a
    whole sector. Drill-down calls this once per client, so the expensive part
    (date parsing) is cached per calibration run on Flask's `g` — only the cheap
    boolean-filter + groupby repeats per call."""
    from flask import g

    from project.db_models.calibration_models import CalibrationRun

    # Cache the resolved CalibrationRun per forecast run — this helper is called
    # once per sector (heatmap overview) or once per client (drill-down), and the
    # bare .get() would otherwise re-fire that identical query every time.
    cal_key = f"_cal_run_{fr.id}"
    cal_run = getattr(g, cal_key, None)
    if cal_run is None:
        cal_run = CalibrationRun.query.get(fr.calibration_run_id)
        setattr(g, cal_key, cal_run if cal_run is not None else False)
    elif cal_run is False:
        return {}
    if not cal_run or not cal_run.target_col:
        return {}
    target = cal_run.target_col

    cache_key = f"_hist_frame_{cal_run.id}"
    work = getattr(g, cache_key, None)
    if work is None:
        ds = Dataset.query.get(cal_run.dataset_id)
        if not ds or not ds.file_path:
            setattr(g, cache_key, pd.DataFrame())
            return {}
        try:
            df = _load_dataset_df(ds)
        except Exception:
            setattr(g, cache_key, pd.DataFrame())
            return {}
        date_col = next(
            (c for c in ("date", "YEAR", "year", "period") if c in df.columns), None
        )
        if not date_col or target not in df.columns:
            setattr(g, cache_key, pd.DataFrame())
            return {}
        work = df.copy()
        work["_year"] = pd.to_datetime(work[date_col], errors="coerce").dt.year
        if work["_year"].isna().all():
            # Already a bare year column (e.g. int 2024)
            work["_year"] = pd.to_numeric(df[date_col], errors="coerce")
        work = work.dropna(subset=["_year"])
        setattr(g, cache_key, work)

    if work.empty or target not in work.columns:
        return {}
    if client_id and "client_id" in work.columns:
        subset = work[work["client_id"] == client_id]
    elif sector and "sector" in work.columns:
        subset = work[work["sector"] == sector]
    else:
        subset = work
    if subset.empty:
        return {}
    grouped = subset.groupby("_year")[target].sum()
    return {int(y): float(v) for y, v in grouped.items()}


def _cached_variable_index(fr: ForecastRun) -> tuple[dict, dict]:
    """Memoized build_variable_index — the heatmap drill-down and forecast screen
    call this once per client row (dozens to hundreds per request); rebuilding the
    segmentation info + prediction index from ForecastRunResult rows each time would
    be an N+1 query pattern.

    Cached on request-scoped `g` and, for successful runs, on the cross-request app
    `cache` keyed by the immutable `run_id` (a succeeded run's results never change,
    so the entry is safe basically forever — TTL is only memory hygiene)."""
    from flask import g

    from project.core.credit_risk.forecast_lookup import build_variable_index

    g_key = f"_variable_index_{fr.id}"
    cached = getattr(g, g_key, None)
    if cached is not None:
        return cached

    xcache_key = f"cr_var_index:{fr.run_id}"
    result = cache.get(xcache_key) if fr.status == "success" else None
    if result is None:
        result = build_variable_index(fr)
        if fr.status == "success":
            cache.set(xcache_key, result, timeout=3600)

    setattr(g, g_key, result)
    return result


def _variable_levels(
    rows_df: pd.DataFrame, fr: ForecastRun, scenario: str, hist: dict
) -> dict:
    """{year: value} — historical actuals merged with the forecast sum across every
    row in rows_df (one sector's clients, or a single client) for one scenario."""
    from project.core.credit_risk.forecast_lookup import lookup_forecast

    seg_info, idx_map = _cached_variable_index(fr)
    totals: dict[int, float] = {}
    for _, r in rows_df.iterrows():
        series = lookup_forecast(
            seg_info,
            idx_map,
            str(r.get("sector") or ""),
            str(r.get("subsector") or ""),
            str(r.get("country") or ""),
        )
        for yr, v in series.get(scenario, {}).items():
            totals[yr] = totals.get(yr, 0.0) + v
    levels = dict(hist)
    levels.update(totals)
    return levels


def _all_scenarios(fr: ForecastRun) -> list[str]:
    _, idx_map = _cached_variable_index(fr)
    scens: set[str] = set()
    for ctx_map in idx_map.values():
        scens.update(ctx_map.keys())
    order = {"Baseline": 0, "Adverse": 1, "Severely Adverse": 2}
    return sorted(scens, key=lambda s: (order.get(s, 99), s))


class AnalysisSeriesPending(Exception):
    """Raised when a run's Heatmap / Forecast level series isn't materialised yet.

    The caller dispatches the Celery backfill and returns 202 so the request never
    blocks on the heavy pandas job (which is what made these pages slow / stall).
    """


def _dispatch_series_backfill(cr):
    """Enqueue the analysis-series backfill once, deduped across concurrent pollers.

    ``cache.add`` sets the lock only if absent, so overlapping heatmap/forecast/meta
    requests (and repeated poll ticks) enqueue the task a single time. The lock TTL
    doubles as a cooldown: if the backfill fails, we won't re-enqueue for 10 min.
    On success the run has rows, so this path isn't reached again regardless.
    """
    from project.workers.tasks import backfill_analysis_series

    if cache.add(f"cr_series_backfill:{cr.run_id}", 1, timeout=600):
        backfill_analysis_series.delay(cr.run_id)


def _series_pending_response(cr):
    _dispatch_series_backfill(cr)
    return jsonify(
        {
            "status": "materializing",
            "message": "Preparing analysis data — this run's series is being computed. "
            "This page will refresh automatically.",
        }
    ), 202


def _analysis_series_materialised(cr) -> bool:
    """Cheap existence probe (one indexed row) — distinguishes an un-materialised
    run from a legitimately-empty scope so callers can return 202 vs 404 correctly."""
    from project.db_models.credit_models import CreditRiskAnalysisSeries

    return (
        db.session.query(CreditRiskAnalysisSeries.id)
        .filter(CreditRiskAnalysisSeries.credit_risk_run_id == cr.id)
        .first()
        is not None
    )


def _load_analysis_series(
    cr, *, scope_type=None, scope_key=None, scope_keys=None, sector=None
):
    """Return the materialised level series for a run as a nested dict:

        series[scope_type][scope_key][slot][scenario] = {year: value}

    plus ``sector_of`` mapping each client scope_key → its sector. Reads exclusively
    from ``credit_risk_analysis_series`` with a lightweight column SELECT — never the
    whole ORM row — and only the scope the caller needs (the heatmap overview wants
    just ``scope_type='sector'``; the forecast wants a single scope_key). Loading the
    entire run's rows was the cost that made these pages slow. If the run isn't
    materialised yet, raises ``AnalysisSeriesPending`` so the endpoint returns 202.
    """
    from project.db_models.credit_models import CreditRiskAnalysisSeries

    if not _analysis_series_materialised(cr):
        raise AnalysisSeriesPending()

    m = CreditRiskAnalysisSeries
    q = db.session.query(
        m.scope_type, m.scope_key, m.sector, m.slot, m.scenario, m.year, m.value
    ).filter(m.credit_risk_run_id == cr.id)
    if scope_type is not None:
        q = q.filter(m.scope_type == scope_type)
    if scope_key is not None:
        q = q.filter(m.scope_key == scope_key)
    if scope_keys is not None:
        q = q.filter(m.scope_key.in_(list(scope_keys)))
    if sector is not None:
        q = q.filter(m.sector == sector)

    series: dict = {}
    sector_of: dict[str, str] = {}
    for st, sk, sec, slot, scen, year, value in q.all():
        series.setdefault(st, {}).setdefault(sk, {}).setdefault(slot, {}).setdefault(
            scen, {}
        )[year] = value
        if st == "client" and sec is not None:
            sector_of[sk] = sec
    return series, sector_of


@credit_risk.get("/analysis/meta")
@require_perm("credit_risk:read")
def get_analysis_meta():
    from project.db_models.credit_models import CreditRiskAnalysisSeries

    try:
        cr = _get_analysis_run(request.args.get("run_id"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    # Sectors, companies and linked forecast targets are fixed for a run (a segment
    # re-fit changes values, not membership), so cache the whole payload per run —
    # only the first hit pays the distinct scan over the client-scope rows.
    cache_key = f"cr_analysis_meta:{cr.run_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    slots = _slot_forecast_runs(cr)

    # Sectors and their companies come straight from the materialised series
    # (distinct client scope_keys + their sector) — an indexed SELECT, instead of
    # downloading and parsing the portfolio from MinIO on every page load.
    pairs = (
        db.session.query(
            CreditRiskAnalysisSeries.scope_key, CreditRiskAnalysisSeries.sector
        )
        .filter(
            CreditRiskAnalysisSeries.credit_risk_run_id == cr.id,
            CreditRiskAnalysisSeries.scope_type == "client",
            CreditRiskAnalysisSeries.sector.isnot(None),
        )
        .distinct()
        .all()
    )
    if not pairs:
        return _series_pending_response(cr)

    companies_by_sector: dict[str, list[str]] = {}
    for client_id, sector in pairs:
        companies_by_sector.setdefault(str(sector), []).append(str(client_id))
    for sector in companies_by_sector:
        companies_by_sector[sector] = sorted(set(companies_by_sector[sector]))

    payload = {
        "run_id": cr.run_id,
        "sectors": sorted(companies_by_sector.keys()),
        "companies_by_sector": companies_by_sector,
        "forecast_targets": [
            {"key": key, "title": title}
            for key, title in credit_analysis.FORECAST_TARGET_SLOTS
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
    cache.set(cache_key, payload, timeout=3600)
    return jsonify(payload), 200


@credit_risk.get("/analysis/heatmap")
@require_perm("credit_risk:read")
def get_analysis_heatmap():
    metric = request.args.get("metric", "revenue_growth")
    if metric not in credit_analysis.HEATMAP_METRICS:
        return jsonify({"error": f"Unknown metric '{metric}'"}), 400
    sector_filter = request.args.get("sector") or None
    clients_arg = request.args.get("clients")
    client_filter = (
        {c.strip() for c in clients_arg.split(",") if c.strip()}
        if clients_arg
        else None
    )

    try:
        cr = _get_analysis_run(request.args.get("run_id"))
        # Load only the scope this view needs: the sector overview reads sector-scope
        # rows; a drilldown reads just the selected companies' client-scope rows.
        # (Loading the whole run's rows is what made this endpoint slow.)
        if sector_filter:
            series, sector_of = _load_analysis_series(
                cr,
                scope_type="client",
                scope_keys=client_filter,
                sector=None if client_filter else sector_filter,
            )
        else:
            series, sector_of = _load_analysis_series(cr, scope_type="sector")
        slots = _slot_forecast_runs(cr)
    except AnalysisSeriesPending:
        return _series_pending_response(cr)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    payload = credit_analysis.build_heatmap(
        series,
        sector_of,
        slots,
        metric=metric,
        sector_filter=sector_filter,
        client_filter=client_filter,
        requested_scenario=request.args.get("scenario"),
    )
    return jsonify(payload), 200


@credit_risk.get("/analysis/forecast")
@require_perm("credit_risk:read")
def get_analysis_forecast():
    sector = request.args.get("sector")
    client_id = request.args.get("client_id") or None
    if not sector:
        return jsonify({"error": "sector is required"}), 400

    requested = request.args.get("targets")
    requested_keys = (
        {t.strip() for t in requested.split(",") if t.strip()} if requested else None
    )
    # Indexing (base year = 100) is opt-in — by default we return raw levels so the
    # chart shows real magnitudes. The client toggles this on when it wants every
    # series rebased to a common 100 for shape comparison.
    indexed = request.args.get("indexed", "false").lower() in ("1", "true", "yes")

    # Scope: a single company if client_id given, else the whole sector — load only
    # that scope's rows rather than the entire run's.
    scope_type, scope_key = ("client", client_id) if client_id else ("sector", sector)

    try:
        cr = _get_analysis_run(request.args.get("run_id"))
        series, _ = _load_analysis_series(
            cr, scope_type=scope_type, scope_key=scope_key
        )
        slots = _slot_forecast_runs(cr)
    except AnalysisSeriesPending:
        return _series_pending_response(cr)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    payload = credit_analysis.build_forecast(
        series,
        slots,
        sector=sector,
        client_id=client_id,
        requested_keys=requested_keys,
        indexed=indexed,
    )
    return jsonify(payload), 200


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
    rating_category = (
        dict(zip(pd_df["Rating"], pd_df["Category"])) if not pd_df.empty else {}
    )

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
    scenario = requested or ("Baseline" if "Baseline" in scenarios else scenarios[0])

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
