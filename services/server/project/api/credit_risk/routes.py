import json
import uuid
from datetime import datetime, timezone

import pandas as pd
from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.orm import selectinload

from project import cache
from project.api.auth.decorators import require_perm
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

    return jsonify(
        {"items": result, "total": runs.total, "page": page, "pages": runs.pages}
    ), 200


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


def _check_workflow_membership(cr: CreditRiskRun):
    """Return a 409 response if this run belongs to a workflow, else None."""
    if cr.workflow_run_id:
        from project.db_models.workflow_models import WorkflowRun

        wf = WorkflowRun.query.get(cr.workflow_run_id)
        wf_name = wf.name if wf else cr.workflow_run_id
        return (
            jsonify(
                {
                    "error": f"This run belongs to workflow '{wf_name}' — delete "
                    "or rerun the workflow instead."
                }
            ),
            409,
        )
    return None


@credit_risk.post("/runs/<cr_run_id>/rerun")
@require_perm("credit_risk:execute")
def rerun_run(cr_run_id: str):
    from project import app_session
    from project.workers.tasks import run_credit_analysis

    cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
    if not cr:
        return jsonify({"error": "Run not found"}), 404
    err = _check_workflow_membership(cr)
    if err:
        return err

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
    err = _check_workflow_membership(cr)
    if err:
        return err

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


# ── Analysis: Sector Heatmap & Financial Forecast ─────────────────────────────
#
# Both screens read from the active CreditRiskRun: its credit + financial-portfolio
# datasets (for sector/subsector/country routing, same merge the Celery task does)
# and its linked ForecastRun "slots". total_assets / short_term_debts /
# long_term_debts are the 3 slots required to run KMV at all; total_revenue and
# total_cogs are optional extra slots (added via the same New Analysis form) that
# unlock these two Analysis screens. "History" comes from the actual dataset each
# forecast run's calibration was trained on (real historical actuals), not mocked.

_HEATMAP_METRICS = {
    "revenue_growth": {
        "label": "Revenue growth",
        "unit": "% YoY",
        "needs": {"total_revenue"},
    },
    "cogs_margin": {
        "label": "COGS / Revenue",
        "unit": "Δ pp",
        "needs": {"total_revenue", "total_cogs"},
    },
    "leverage": {
        "label": "Net debt / EBITDA",
        "unit": "Δ turns",
        "needs": {"total_revenue", "total_cogs", "short_term_debts", "long_term_debts"},
    },
}

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


def _load_dataset_df(dataset) -> pd.DataFrame:
    """Download + parse a Dataset's file from MinIO — same object-key convention
    as the credit-risk analysis Celery task (`run_credit_analysis`).

    Two cache layers: request-scoped `g` (one request can reference the same
    dataset several times) and the cross-request app `cache` keyed by dataset id +
    file_path. A dataset's file is immutable per file_path (a re-upload gets a new
    path), so the cross-request entry never goes stale and only needs a TTL for
    memory hygiene. This is the fix for re-downloading + re-parsing on every
    heatmap/forecast request and every 5 s poll."""
    import io

    from flask import g

    from project.core import storage

    g_key = f"_dataset_df_{dataset.id}"
    cached = getattr(g, g_key, None)
    if cached is not None:
        return cached

    xcache_key = f"cr_dataset_df:{dataset.id}:{dataset.file_path}"
    df = cache.get(xcache_key)
    if df is None:
        file_bytes = storage.download_bytes(dataset.file_path.split("/", 1)[-1])
        ext = dataset.file_path.rsplit(".", 1)[-1].lower()
        buf = io.BytesIO(file_bytes)
        if ext == "csv":
            df = pd.read_csv(buf)
        elif ext == "xlsx":
            df = pd.read_excel(buf)
        elif ext == "parquet":
            df = pd.read_parquet(buf)
        else:
            raise ValueError(f"Unsupported file type: {ext}")
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
    from project.db_models.credit_models import CreditRiskForecastInput

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


_SERIES_HISTORY = "History"


def _load_analysis_series(cr):
    """Return the materialised level series for a run as a nested dict:

        series[scope_type][scope_key][slot][scenario] = {year: value}

    plus ``sector_of`` mapping each client scope_key → its sector. Reads from
    ``credit_risk_analysis_series``; if a successful run has no rows yet (predates
    materialisation, or the worker's best-effort step failed), it computes and
    persists them once now (lazy backfill) so subsequent loads are fast.
    """
    from project.db_models.credit_models import CreditRiskAnalysisSeries

    rows = CreditRiskAnalysisSeries.query.filter_by(credit_risk_run_id=cr.id).all()
    if not rows:
        from project.core.credit_risk.analysis_series import (
            materialize_analysis_series,
        )

        portfolio_df = _analysis_portfolio_df(cr)
        slots = _slot_forecast_runs(cr)
        materialize_analysis_series(cr, portfolio_df, slots)
        rows = CreditRiskAnalysisSeries.query.filter_by(credit_risk_run_id=cr.id).all()

    series: dict = {}
    sector_of: dict[str, str] = {}
    for r in rows:
        series.setdefault(r.scope_type, {}).setdefault(r.scope_key, {}).setdefault(
            r.slot, {}
        ).setdefault(r.scenario, {})[r.year] = r.value
        if r.scope_type == "client" and r.sector is not None:
            sector_of[r.scope_key] = r.sector
    return series, sector_of


def _series_levels(series, scope_type, scope_key, slot, scenario) -> dict:
    """One {year: value} level series from the loaded materialised structure."""
    return series.get(scope_type, {}).get(scope_key, {}).get(slot, {}).get(scenario, {})


@credit_risk.get("/analysis/meta")
@require_perm("credit_risk:read")
def get_analysis_meta():
    try:
        cr = _get_analysis_run(request.args.get("run_id"))
        portfolio_df = _analysis_portfolio_df(cr)
        slots = _slot_forecast_runs(cr)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    if "sector" not in portfolio_df.columns:
        return jsonify({"error": "This run's portfolio has no 'sector' column"}), 422

    companies_by_sector: dict[str, list[str]] = {}
    for sector, grp in portfolio_df.groupby("sector"):
        companies_by_sector[str(sector)] = sorted(
            grp["client_id"].astype(str).unique().tolist()
        )

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


@credit_risk.get("/analysis/heatmap")
@require_perm("credit_risk:read")
def get_analysis_heatmap():
    metric = request.args.get("metric", "revenue_growth")
    if metric not in _HEATMAP_METRICS:
        return jsonify({"error": f"Unknown metric '{metric}'"}), 400
    sector_filter = request.args.get("sector") or None
    clients_arg = request.args.get("clients")
    client_filter = (
        {c.strip() for c in clients_arg.split(",") if c.strip()}
        if clients_arg
        else None
    )
    spec = _HEATMAP_METRICS[metric]

    try:
        cr = _get_analysis_run(request.args.get("run_id"))
        series, sector_of = _load_analysis_series(cr)
        slots = _slot_forecast_runs(cr)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    missing = spec["needs"] - set(slots)
    if missing:
        return jsonify(
            {
                "error": f"This metric needs forecast inputs for: {', '.join(sorted(missing))}. "
                "Link them on the active analysis run."
            }
        ), 422

    # The forecast run itself (not the historical dataset) defines which years are
    # "forecast" columns — using an arbitrary year cutoff would misalign whenever a
    # forecast doesn't happen to start the year right after the training data ends.
    anchor_fr = (
        slots.get("total_revenue")
        or slots.get("total_cogs")
        or slots.get("short_term_debts")
        or slots.get("long_term_debts")
    )
    _, anchor_idx = _cached_variable_index(anchor_fr)
    forecast_years = sorted(
        {yr for ctx_map in anchor_idx.values() for yr in ctx_map.get("Baseline", {})}
    )

    def combined_levels(scope_type, scope_key, slot) -> dict:
        """History merged with the Baseline forecast for one slot/scope — the same
        {year: value} that _variable_levels(rows_df, fr, 'Baseline', hist) produced,
        now read straight from the materialised table."""
        levels = dict(
            _series_levels(series, scope_type, scope_key, slot, _SERIES_HISTORY)
        )
        levels.update(_series_levels(series, scope_type, scope_key, slot, "Baseline"))
        return levels

    def metric_series(scope_type, scope_key) -> dict:
        rev = combined_levels(scope_type, scope_key, "total_revenue")
        cogs = combined_levels(scope_type, scope_key, "total_cogs")
        st = combined_levels(scope_type, scope_key, "short_term_debts")
        lt = combined_levels(scope_type, scope_key, "long_term_debts")

        if metric == "revenue_growth":
            series_out = rev
        elif metric == "cogs_margin":
            years = sorted(set(rev) & set(cogs))
            series_out = {y: (cogs[y] / rev[y] * 100) for y in years if rev[y]}
        else:  # leverage
            years = sorted(set(rev) & set(cogs) & set(st) & set(lt))
            series_out = {}
            for y in years:
                ebitda = rev[y] - cogs[y]
                if ebitda:
                    series_out[y] = (st[y] + lt[y]) / ebitda
        return series_out

    def yoy_deltas(series: dict, target_years: list[int]) -> list[float | None]:
        all_years = sorted(series.keys())
        out = []
        for y in target_years:
            prior = [yy for yy in all_years if yy < y]
            if y not in series or not prior:
                out.append(None)
                continue
            prev_y = prior[-1]
            prev_v, cur_v = series[prev_y], series[y]
            if metric == "revenue_growth":
                out.append(
                    round((cur_v - prev_v) / prev_v * 100, 1) if prev_v else None
                )
            else:
                out.append(round(cur_v - prev_v, 1))
        return out

    if sector_filter:
        # Clients belonging to the drilled sector (from the materialised rows).
        sector_clients = sorted(
            cid for cid, sec in sector_of.items() if sec == sector_filter
        )
        if not sector_clients:
            return jsonify({"error": f"Sector '{sector_filter}' not found"}), 404
        # Only return the companies the caller asked for.
        if client_filter is not None:
            sector_clients = [c for c in sector_clients if c in client_filter]
            if not sector_clients:
                return jsonify(
                    {"error": "None of the selected companies are in this sector"}
                ), 404
        rows_out = []
        for client_id in sector_clients:
            series_c = metric_series("client", client_id)
            rows_out.append(
                {
                    "key": client_id,
                    "label": client_id,
                    "drillable": False,
                    "values": yoy_deltas(series_c, forecast_years),
                }
            )
        return jsonify(
            {
                "metric": metric,
                "label": spec["label"],
                "unit": spec["unit"],
                "years": forecast_years,
                "drilled": True,
                "title": sector_filter,
                "subtitle": f"Company-level {spec['label'].lower()} across forecast years",
                "rows": rows_out,
            }
        ), 200

    sectors = sorted(series.get("sector", {}).keys())
    rows_out = []
    for sector in sectors:
        series_s = metric_series("sector", sector)
        rows_out.append(
            {
                "key": sector,
                "label": sector,
                "drillable": True,
                "values": yoy_deltas(series_s, forecast_years),
            }
        )

    return jsonify(
        {
            "metric": metric,
            "label": spec["label"],
            "unit": spec["unit"],
            "years": forecast_years,
            "drilled": False,
            "title": "Sector Heatmap",
            "subtitle": "Forecasted change by sector and year",
            "rows": rows_out,
        }
    ), 200


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

    try:
        cr = _get_analysis_run(request.args.get("run_id"))
        series, _ = _load_analysis_series(cr)
        slots = _slot_forecast_runs(cr)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    # Scope: a single company if client_id given, else the whole sector.
    if client_id:
        scope_type, scope_key = "client", client_id
        if scope_key not in series.get("client", {}):
            return jsonify({"error": "No matching clients found"}), 404
    else:
        scope_type, scope_key = "sector", sector
        if scope_key not in series.get("sector", {}):
            return jsonify({"error": "No matching clients found"}), 404

    def series_points(levels: dict) -> list[dict]:
        return [{"year": y, "value": round(levels[y], 4)} for y in sorted(levels)]

    def _scenarios_for(slot_key: str) -> list[str]:
        present = set(
            series.get(scope_type, {}).get(scope_key, {}).get(slot_key, {}).keys()
        )
        present.discard(_SERIES_HISTORY)
        order = {"Baseline": 0, "Adverse": 1, "Severely Adverse": 2}
        return sorted(present, key=lambda s: (order.get(s, 99), s))

    metrics_out = []
    for slot_key, title in _FORECAST_TARGET_SLOTS:
        fr = slots.get(slot_key)
        if not fr:
            continue
        if requested_keys is not None and slot_key not in requested_keys:
            continue

        hist = _series_levels(series, scope_type, scope_key, slot_key, _SERIES_HISTORY)
        base_year = min(hist) if hist else None
        base_val = hist.get(base_year) if base_year is not None else None

        def to_series(levels: dict, base_val=base_val) -> list[dict]:
            if not indexed or not base_val:
                return series_points(levels)
            return [
                {"year": y, "value": round(levels[y] / base_val * 100, 2)}
                for y in sorted(levels)
            ]

        history_points = to_series(hist)
        scenarios_out = {}
        for scen in _scenarios_for(slot_key):
            levels = _series_levels(series, scope_type, scope_key, slot_key, scen)
            scenarios_out[scen] = to_series(levels)

        baseline_pts = scenarios_out.get("Baseline", [])
        metrics_out.append(
            {
                "key": slot_key,
                "title": title,
                "unit": (
                    f"Indexed · {base_year} = 100" if indexed and base_year else "Level"
                ),
                "indexed": bool(indexed and base_val),
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

    return jsonify(
        {"sector": sector, "client_id": client_id, "metrics": metrics_out}
    ), 200
