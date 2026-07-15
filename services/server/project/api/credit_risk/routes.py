import json
import os
from datetime import datetime, timezone

import pandas as pd
from flask import current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity

from project import DATA_STORE, app_session, cache
from project.api.auditlog.decorators import audit_action
from project.api.auth.decorators import require_perm
from project.api.utils import paginate_logs
from project.core import table_query
from project.db_models.calibration_models import Dataset
from project.db_models.credit_models import (
    CreditRiskAnalysisSeries,
    CreditRiskResult,
    CreditRiskRun,
    CreditRiskRunLog,
)
from project.schemas.credit_risk import CreateCreditRiskRun
from project.services import credit_risk as credit_risk_service
from project.services import credit_risk_analysis as analysis_service
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


_pd_rating_df = credit_risk_service.pd_rating_df


# ── v2 endpoints ──────────────────────────────────────────────────────────────


@credit_risk.get("/pd-ratings")
@require_perm("credit_risk:read")
def get_pd_ratings():
    curve = request.args.get("curve", "moodys")
    return jsonify(credit_risk_service.list_pd_ratings(curve)), 200


@credit_risk.get("/clients")
@require_perm("credit_risk:read")
def get_clients():

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
    return jsonify(
        credit_risk_service.list_runs(
            page=request.args.get("page", 1, type=int),
            per_page=request.args.get("per_page", 50, type=int),
        )
    ), 200


@credit_risk.post("/runs")
@require_perm("credit_risk:execute")
@audit_action(
    "Launch",
    "analysis",
    "credit_risk",
    database_involved="credit_risk_runs",
    describe=lambda kw, body: (
        f"User [$USER] launched credit risk analysis run {(body or {}).get('run_id', '')}"
    ),
)
def create_run():
    payload = CreateCreditRiskRun.model_validate(request.get_json(silent=True) or {})
    cr_dict = credit_risk_service.create_run(payload, get_jwt_identity())
    return jsonify(cr_dict), 202


@credit_risk.get("/runs/active")
@require_perm("credit_risk:read")
def get_active_run():
    return jsonify(credit_risk_service.get_run(None)), 200


@credit_risk.put("/runs/<cr_run_id>/active")
@require_perm("credit_risk:execute")
@audit_action(
    "Activate",
    "analysis",
    "credit_risk",
    database_involved="credit_risk_runs",
    describe=lambda kw, body: (
        f"User [$USER] set credit risk run {kw.get('cr_run_id')} as active"
    ),
)
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
@audit_action(
    "Rerun",
    "analysis",
    "credit_risk",
    database_involved="credit_risk_runs",
    describe=lambda kw, body: (
        f"User [$USER] re-ran credit risk analysis run {kw.get('cr_run_id')}"
    ),
)
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
@audit_action(
    "Cancel",
    "analysis",
    "credit_risk",
    database_involved="credit_risk_runs",
    describe=lambda kw, body: (
        f"User [$USER] cancelled credit risk analysis run {kw.get('cr_run_id')}"
    ),
)
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


@credit_risk.get("/runs/<cr_run_id>/results")
@require_perm("credit_risk:read")
def get_run_results(cr_run_id: str):
    return jsonify(
        credit_risk_service.get_run_results(
            cr_run_id,
            page=int(request.args.get("page", 0)),
            page_size=int(request.args.get("page_size", 50)),
            sort_column=request.args.get("sort_column"),
            sort_order=request.args.get("sort_order"),
            filters=table_query.parse_filters(request.args.get("filters")),
        )
    ), 200


@credit_risk.get("/runs/<cr_run_id>/results/distinct")
@require_perm("credit_risk:read")
def get_run_results_distinct(cr_run_id: str):
    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404
    column = request.args.get("column", "")
    if not column:
        return jsonify({"values": [], "truncated": False}), 200

    df = credit_risk_service.run_results_df(cr)
    return jsonify(table_query.distinct_values(df, column)), 200


@credit_risk.delete("/runs/<cr_run_id>")
@require_perm("credit_risk:write")
@audit_action(
    "Delete",
    "analysis",
    "credit_risk",
    database_involved="credit_risk_runs",
    describe=lambda kw, body: (
        f"User [$USER] deleted credit risk analysis run {kw.get('cr_run_id')}"
    ),
)
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
    return jsonify(credit_risk_service.get_run(cr_run_id)), 200


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
    return jsonify(credit_risk_service.get_client_result(cr_run_id, client_id)), 200


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
# All the loaders/builders live in project/services/credit_risk_analysis.py
# (shared with the MCP tools and the Celery materializer); these routes only
# parse args and map AnalysisSeriesPending → 202.


def _series_pending_response(exc: analysis_service.AnalysisSeriesPending):
    return jsonify(analysis_service.series_pending_payload(exc.run)), 202


@credit_risk.get("/analysis/meta")
@require_perm("credit_risk:read")
def get_analysis_meta():
    try:
        payload = analysis_service.get_analysis_meta(request.args.get("run_id"))
    except analysis_service.AnalysisSeriesPending as exc:
        return _series_pending_response(exc)
    return jsonify(payload), 200


@credit_risk.get("/analysis/heatmap")
@require_perm("credit_risk:read")
def get_analysis_heatmap():
    clients_arg = request.args.get("clients")
    client_filter = (
        {c.strip() for c in clients_arg.split(",") if c.strip()}
        if clients_arg
        else None
    )

    try:
        payload = analysis_service.get_analysis_heatmap(
            request.args.get("metric", "revenue_growth"),
            run_id=request.args.get("run_id"),
            sector=request.args.get("sector") or None,
            clients=client_filter,
            scenario=request.args.get("scenario"),
        )
    except analysis_service.AnalysisSeriesPending as exc:
        return _series_pending_response(exc)
    return jsonify(payload), 200


@credit_risk.get("/analysis/forecast")
@require_perm("credit_risk:read")
def get_analysis_forecast():
    requested = request.args.get("targets")
    requested_keys = (
        {t.strip() for t in requested.split(",") if t.strip()} if requested else None
    )

    try:
        payload = analysis_service.get_analysis_forecast(
            request.args.get("sector"),
            run_id=request.args.get("run_id"),
            client_id=request.args.get("client_id") or None,
            requested_keys=requested_keys,
            # Indexing (base year = 100) is opt-in — by default raw levels so the
            # chart shows real magnitudes.
            indexed=request.args.get("indexed", "false").lower()
            in ("1", "true", "yes"),
        )
    except analysis_service.AnalysisSeriesPending as exc:
        return _series_pending_response(exc)
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
    cr = analysis_service.get_analysis_run(request.args.get("run_id"))
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
