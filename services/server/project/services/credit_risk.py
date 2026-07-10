"""Credit-risk run orchestration and reads (transport-agnostic).

Shared by the Flask routes and the MCP tools. No Flask imports — callers
supply plain arguments and receive dicts (or a DomainError).
"""

import json
import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import selectinload

from project import app_session, cache
from project.constants import LaunchOrigin, RunStatus
from project.core import table_query
from project.db_models.calibration_models import Dataset
from project.db_models.credit_models import (
    CreditRiskForecastInput,
    CreditRiskResult,
    CreditRiskRun,
    PdRating,
)
from project.db_models.forecast_models import ForecastRun
from project.db_models.workflow_models import WorkflowRun
from project.exceptions import BadRequestError, NotFoundError
from project.schemas.credit_risk import CreateCreditRiskRun
from project.services._pagination import pagination_envelope
from project.workers.tasks import run_credit_analysis

_REQUIRED_SLOTS = {"total_assets", "short_term_debts", "long_term_debts"}


def create_run(
    payload: CreateCreditRiskRun,
    identity: str,
    origin: str = LaunchOrigin.MANUAL,
) -> dict:
    """Validate + create a CreditRiskRun (+ forecast-input FKs) and dispatch
    ``run_credit_analysis``. ``origin`` records how it was launched (MANUAL from
    HTTP, AUTO from MCP). Raises ``NotFoundError`` (404) / ``BadRequestError`` (400).
    """
    ds = Dataset.query.get(payload.dataset_id)
    if not ds:
        raise NotFoundError("Dataset not found")

    fin_id = payload.financial_portfolio_dataset_id
    if fin_id:
        if not Dataset.query.get(fin_id):
            raise NotFoundError("Financial portfolio dataset not found")

    forecast_inputs = payload.cal_inputs or {}
    missing = _REQUIRED_SLOTS - {k for k, v in forecast_inputs.items() if v}
    if missing:
        raise BadRequestError(f"Missing required forecast inputs: {sorted(missing)}")

    # Resolve each slot's UUID to its forecast run — validates existence/success
    # and becomes the FK reference that blocks accidental deletion of the run.
    slot_to_forecast_run: dict[str, ForecastRun] = {}
    for slot, run_uuid in forecast_inputs.items():
        fr = ForecastRun.query.filter_by(run_id=run_uuid).first()
        if not fr or fr.status != RunStatus.SUCCESS:
            raise BadRequestError(
                f"Forecast run for '{slot}' not found or not successful"
            )
        slot_to_forecast_run[slot] = fr

    cr_run_id = str(uuid.uuid4())
    with app_session() as s:
        cr = CreditRiskRun(
            run_id=cr_run_id,
            dataset_id=payload.dataset_id,
            financial_portfolio_dataset_id=fin_id,
            is_active=False,
            exposure=payload.exposure,
            discount_rate=payload.discount_rate,
            lifetime_horizon=payload.lifetime_horizon,
            curve=payload.curve,
            status=RunStatus.QUEUED,
            triggered_by=identity,
            origin=origin,
            created_at=datetime.now(timezone.utc),
        )
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
    return cr_dict


def list_runs(page: int = 1, per_page: int = 50) -> dict:
    """Paginated credit-risk run list, newest first."""
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

    return pagination_envelope(result, runs)


def get_run(run_id: str | None = None) -> dict:
    """One credit-risk run with its dataset name and result client ids.

    ``run_id=None`` resolves the active run. Raises ``NotFoundError`` (404).
    """
    if run_id:
        cr = CreditRiskRun.query.filter_by(run_id=run_id).first()
        if not cr:
            raise NotFoundError("Run not found")
    else:
        cr = CreditRiskRun.query.filter_by(is_active=True).first()
        if not cr:
            raise NotFoundError("No active run")

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
    if cr.workflow_run_id:
        wf = WorkflowRun.query.get(cr.workflow_run_id)
        d["workflow_run_uuid"] = wf.run_id if wf else None
    return d


def pd_rating_df(curve: str = "moodys") -> pd.DataFrame:
    """The rating→PD curve as the Category/Rating/PD frame the KMV core expects."""
    rows = PdRating.query.filter_by(curve_name=curve).order_by(PdRating.category).all()
    return pd.DataFrame(
        [{"Category": r.category, "Rating": r.rating, "PD": r.pd} for r in rows]
    )


def list_pd_ratings(curve: str = "moodys") -> list[dict]:
    """All rating rows of one PD curve, best category first."""
    rows = PdRating.query.filter_by(curve_name=curve).order_by(PdRating.category).all()
    return [r.to_dict() for r in rows]


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


def run_results_df(cr: CreditRiskRun) -> pd.DataFrame:
    """Per-client PD/LGD/ECL/stage summary rows for a run, as a frame.

    Cached under ``cr_run_results:<run_id>`` — the exact key the segment-recompute
    worker deletes to invalidate (do not rename).
    """
    cache_key = f"cr_run_results:{cr.run_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    results = (
        CreditRiskResult.query.filter_by(run_id=cr.run_id)
        .order_by(CreditRiskResult.id)
        .all()
    )

    pd_rating = pd_rating_df(cr.curve)
    rating_to_category = dict(zip(pd_rating["Rating"], pd_rating["Category"]))
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


def get_run_results(
    run_id: str,
    page: int = 0,
    page_size: int = 50,
    sort_column: str | None = None,
    sort_order: str | None = None,
    filters: list | None = None,
) -> dict:
    """One filtered/sorted page of a run's per-client summary rows.

    ``filters`` is the already-parsed ``table_query`` filter list. Raises
    ``NotFoundError`` (404).
    """
    cr = CreditRiskRun.query.filter_by(run_id=run_id).first()
    if not cr:
        raise NotFoundError("Run not found")
    df = run_results_df(cr)
    page_df, total = table_query.query_page(
        df,
        page=page,
        page_size=page_size,
        sort_column=sort_column,
        sort_order=sort_order,
        filters=filters,
    )
    rows = page_df.where(pd.notnull(page_df), None).to_dict(orient="records")
    return {"rows": rows, "total": total}


def get_client_result(run_id: str, client_id: str) -> dict:
    """One client's full KMV + ECL year×scenario rows for a run.

    Raises ``NotFoundError`` (404).
    """
    result = CreditRiskResult.query.filter_by(
        run_id=run_id, client_id=client_id
    ).first()
    if not result:
        raise NotFoundError("Result not found")
    return {
        "kmv": json.loads(result.kmv_json or "[]"),
        "ecl": json.loads(result.ecl_json or "[]"),
    }
