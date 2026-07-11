"""Forecast-run orchestration and reads (transport-agnostic).

Shared by the Flask routes and the MCP tools. No Flask imports — callers
supply plain arguments and receive dicts (or a DomainError).
"""

import json
import uuid
from datetime import datetime, timezone

import pandas as pd

from project import app_session, cache, db
from project.constants import LaunchOrigin, RunStatus
from project.core import table_query
from project.core.table_query import DISTINCT_VALUES_LIMIT
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunSegment,
    Dataset,
    ModelConfig,
)
from project.db_models.forecast_models import ForecastRun, ForecastRunResult
from project.db_models.workflow_models import WorkflowRun
from project.exceptions import BadRequestError, NotFoundError
from project.schemas.forecast_runs import CreateForecastRun
from project.services._pagination import pagination_envelope
from project.workers.tasks import run_forecast

# meta_json keys promoted to indexed columns on forecast_run_results. segment_key
# was promoted earlier; the rest are added by migration c3d5e7f9a1b3.
PROMOTED_DIMENSIONS = ("sector", "subsector", "country", "scenario", "segment_key")


def promoted_dims_from_meta(meta: dict) -> dict:
    """Subset of a meta row limited to the promoted dimension columns present."""
    return {k: meta[k] for k in PROMOTED_DIMENSIONS if meta.get(k) is not None}


def create_run(
    payload: CreateForecastRun,
    identity: str,
    origin: str = LaunchOrigin.MANUAL,
) -> dict:
    """Validate + create a ForecastRun and dispatch ``run_forecast``.

    ``origin`` records how it was launched (MANUAL from HTTP, AUTO from MCP).
    Raises ``NotFoundError`` (404) / ``BadRequestError`` (400).
    """
    cal_run = CalibrationRun.query.filter_by(run_id=payload.calibration_run_id).first()
    if not cal_run:
        raise NotFoundError("Calibration run not found")
    if cal_run.status != RunStatus.SUCCESS:
        raise BadRequestError("Calibration run must be in success status")

    segment_key = payload.segment_key or None
    if segment_key:
        seg = CalibrationRunSegment.query.filter_by(
            calibration_run_id=cal_run.id, segment_key=segment_key
        ).first()
        if not seg:
            raise NotFoundError(
                f"Segment '{segment_key}' not found under this calibration run"
            )
        if seg.status != RunStatus.SUCCESS:
            raise BadRequestError(
                f"Segment '{segment_key}' has not completed successfully"
            )
    elif not cal_run.seg_sectors_json and not cal_run.artifact_path:
        # Non-segmented runs need the top-level artifact; segmented runs score
        # every trained segment against the forecast dataset.
        raise BadRequestError("Calibration run has no saved model artifact")

    ds = Dataset.query.get(payload.dataset_id)
    if not ds:
        raise NotFoundError("Dataset not found")
    if not ds.file_path:
        raise BadRequestError(
            "Dataset has no file — live query results are not supported"
        )

    run_id = str(uuid.uuid4())
    with app_session() as s:
        fr = ForecastRun(
            run_id=run_id,
            name=payload.name or None,
            calibration_run_id=cal_run.id,
            dataset_id=payload.dataset_id,
            segment_key=segment_key,
            status=RunStatus.QUEUED,
            triggered_by=identity,
            origin=origin,
            created_at=datetime.now(timezone.utc),
            progress=0,
        )
        s.add(fr)
        s.flush()
        fr_dict = fr.to_dict()

    run_forecast.delay(run_id)
    return fr_dict


def list_runs(page: int = 1, per_page: int = 50, status: str | None = None) -> dict:
    """Paginated forecast-run list, newest first."""
    q = ForecastRun.query
    if status:
        q = q.filter_by(status=status)
    runs = q.order_by(ForecastRun.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    items = runs.items

    # Batch-load the related rows so ForecastRun.to_dict() doesn't fire three
    # per-row queries (was 1 + 3N; now a handful of IN(...) lookups).
    cal_ids = {r.calibration_run_id for r in items}
    ds_ids = {r.dataset_id for r in items}
    cals = (
        {c.id: c for c in CalibrationRun.query.filter(CalibrationRun.id.in_(cal_ids))}
        if cal_ids
        else {}
    )
    cfg_ids = {c.model_config_id for c in cals.values()}
    cfgs = (
        {m.id: m for m in ModelConfig.query.filter(ModelConfig.id.in_(cfg_ids))}
        if cfg_ids
        else {}
    )
    datasets = (
        {d.id: d for d in Dataset.query.filter(Dataset.id.in_(ds_ids))}
        if ds_ids
        else {}
    )

    result = []
    for r in items:
        cal = cals.get(r.calibration_run_id)
        cfg = cfgs.get(cal.model_config_id) if cal else None
        result.append(
            r.to_dict(
                cal_run=cal,
                dataset=datasets.get(r.dataset_id),
                config_name=cfg.name if cfg else None,
            )
        )

    return pagination_envelope(result, runs)


def get_run(run_id: str) -> dict:
    """One forecast run (with its workflow UUID when workflow-owned).

    Raises ``NotFoundError`` (404).
    """
    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        raise NotFoundError("Not found")
    d = fr.to_dict()
    if fr.workflow_run_id:
        wf = WorkflowRun.query.get(fr.workflow_run_id)
        d["workflow_run_uuid"] = wf.run_id if wf else None
    return d


def results_df(fr: ForecastRun) -> pd.DataFrame:
    """All of a run's result rows (date/predicted + meta columns) as a frame."""
    rows = (
        ForecastRunResult.query.filter_by(forecast_run_id=fr.id)
        .order_by(ForecastRunResult.id)
        .all()
    )
    records = []
    for r in rows:
        try:
            meta = json.loads(r.meta_json) if r.meta_json else {}
        except (TypeError, ValueError):
            meta = {}
        records.append({"date": r.date, "predicted": r.predicted, **meta})
    return pd.DataFrame.from_records(records)


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


def invalidate_facets(run_id: str) -> None:
    """Drop a run's cached facets — call after any write that could change its
    result rows (segment re-score)."""
    cache.delete(_FACETS_KEY.format(run_id=run_id))


def get_results(
    run_id: str,
    page: int = 0,
    page_size: int = 50,
    sort_column: str | None = None,
    sort_order: str | None = None,
    filters: list | None = None,
) -> dict:
    """One filtered/sorted page of a run's forecast results.

    ``filters`` is the already-parsed ``table_query`` filter list (callers parse
    their transport's raw value via ``table_query.parse_filters``). Raises
    ``NotFoundError`` (404).
    """
    fr = ForecastRun.query.filter_by(run_id=run_id).first()
    if not fr:
        raise NotFoundError("Not found")
    df = results_df(fr)
    page_df, total = table_query.query_page(
        df,
        page=page,
        page_size=page_size,
        sort_column=sort_column,
        sort_order=sort_order,
        filters=filters,
    )
    rows = page_df.where(pd.notnull(page_df), None).to_dict(orient="records")
    return {"rows": rows, "total": total, "columns": list(df.columns)}
