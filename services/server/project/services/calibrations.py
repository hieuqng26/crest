"""Calibration-run orchestration and reads (transport-agnostic).

Shared by the Flask routes and the MCP tools. No Flask imports — callers
supply plain arguments and receive dicts (or a DomainError).
"""

import json
import uuid

from sqlalchemy.orm import selectinload

from project import app_session
from project.constants import LaunchOrigin, RunStatus
from project.core.calibration_launch import (
    build_search_config_json,
    validate_segmentation,
)
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunSegment,
    Dataset,
    ModelConfig,
)
from project.db_models.workflow_models import WorkflowRun
from project.exceptions import BadRequestError, ConflictError, NotFoundError
from project.schemas.calibrations import CreateCalibrationRun
from project.services._pagination import pagination_envelope
from project.workers.tasks import run_calibration


def create_run(
    payload: CreateCalibrationRun,
    identity: str,
    origin: str = LaunchOrigin.MANUAL,
) -> dict:
    """Validate + create a CalibrationRun and dispatch ``run_calibration``.

    ``origin`` records how it was launched (``LaunchOrigin.MANUAL`` from the
    HTTP wizard, ``AUTO`` from MCP) — the AUTO/MANUAL tag in job history.
    Raises ``NotFoundError`` (404) / ``BadRequestError`` (400).
    """
    ds = Dataset.query.get(payload.dataset_id)
    if not ds:
        raise NotFoundError("Dataset not found")
    cfg = ModelConfig.query.get(payload.model_config_id)
    if not cfg:
        raise NotFoundError("ModelConfig not found")

    parsed_seg, seg_error = validate_segmentation(payload.segmentation or None)
    if seg_error:
        raise BadRequestError(seg_error)

    run_name = (payload.name or "").strip() or None
    run_id = str(uuid.uuid4())
    with app_session() as session:
        run = CalibrationRun(
            run_id=run_id,
            name=run_name,
            dataset_id=ds.id,
            model_config_id=cfg.id,
            status=RunStatus.QUEUED,
            triggered_by=identity,
            origin=origin,
            search_config_json=build_search_config_json(cfg),
            train_split=cfg.train_split if cfg.train_split is not None else 0.8,
            scaler=cfg.scaler,
            target_col=payload.target_col or None,
            feature_cols_json=json.dumps(payload.feature_cols),
            seg_sectors_json=parsed_seg["seg_sectors_json"],
            seg_split_by=parsed_seg["seg_split_by"],
            seg_max_segments=parsed_seg["seg_max_segments"],
            seg_sector_overrides_json=parsed_seg["seg_sector_overrides_json"],
        )
        session.add(run)
        session.flush()
        result = run.to_dict()

    run_calibration.delay(run_id)
    return result


def _run_summary(run: CalibrationRun) -> dict:
    """``to_dict()`` enriched with the config/dataset names the list and detail
    views both display."""
    d = run.to_dict()
    d["config_name"] = run.model_config.name if run.model_config else None
    d["run_name"] = run.name or d["config_name"]
    d["dataset_name"] = run.dataset.name if run.dataset else None
    d["algorithm"] = run.model_config.algorithm if run.model_config else None
    d["model_family"] = run.model_config.family if run.model_config else None
    return d


def list_runs(page: int = 1, per_page: int = 50, status: str | None = None) -> dict:
    """Paginated calibration-run list, newest first."""
    q = (
        CalibrationRun.query.options(
            selectinload(CalibrationRun.model_config),
            selectinload(CalibrationRun.dataset),
        )
        .join(Dataset, CalibrationRun.dataset_id == Dataset.id)
        .join(ModelConfig, CalibrationRun.model_config_id == ModelConfig.id)
        .order_by(CalibrationRun.started_at.desc())
    )
    if status:
        q = q.filter(CalibrationRun.status == status)

    runs = q.paginate(page=page, per_page=per_page, error_out=False)
    return pagination_envelope([_run_summary(r) for r in runs.items], runs)


def get_run(run_id: str) -> dict:
    """One calibration run with retraining/workflow context.

    Raises ``NotFoundError`` (404).
    """
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        raise NotFoundError("Not found")
    d = _run_summary(run)
    # A segment re-run leaves this run at "success"; expose the in-flight count so
    # the job page can show a "Retraining" state and keep polling until it lands.
    d["retraining_segment_count"] = (
        CalibrationRunSegment.query.filter(
            CalibrationRunSegment.calibration_run_id == run.id,
            CalibrationRunSegment.status.in_(("queued", "running")),
        ).count()
        if run.seg_sectors_json is not None
        else 0
    )
    if run.workflow_run_id:
        wf = WorkflowRun.query.get(run.workflow_run_id)
        d["workflow_run_uuid"] = wf.run_id if wf else None
    return d


# The per-observation validation arrays are what make the segment metrics blobs
# huge. List/summary views never need them — the actual-vs-predicted scatter
# fetches them for the ONE selected segment via the diagnostics endpoint.
# `residuals`/`fitted` are kept: they're single arrays the aggregate residual
# histogram sums across segments, and dropping them would break that view.
HEAVY_METRIC_KEYS = ("val_obs", "train_obs")


def slim_metrics(m):
    """Drop the big per-observation arrays from a metrics dict, keeping the rest."""
    if not isinstance(m, dict):
        return m
    return {k: v for k, v in m.items() if k not in HEAVY_METRIC_KEYS}


def get_diagnostics(
    run_id: str, segment_key: str | None = None, *, slim: bool = False
) -> dict:
    """Validation metrics for a run (or one of its segments).

    ``slim=True`` drops the multi-MB per-observation arrays (``val_obs`` /
    ``train_obs``) — the MCP tools always pass it. Raises ``NotFoundError``
    (404) / ``ConflictError`` (409, run or segment not successful).
    """
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        raise NotFoundError("Not found")
    if run.status != "success":
        raise ConflictError(f"Run is {run.status}, diagnostics not available")

    if segment_key:
        seg = CalibrationRunSegment.query.filter_by(
            calibration_run_id=run.id, segment_key=segment_key
        ).first()
        if not seg:
            raise NotFoundError(f"Segment '{segment_key}' not found")
        if seg.status != "success":
            raise ConflictError(f"Segment is {seg.status}")
        metrics = json.loads(seg.val_metrics_json or "{}")
        return {
            "run_id": run_id,
            "segment_key": segment_key,
            "sector": seg.sector,
            "split_value": seg.split_value,
            "config_name": run.model_config.name if run.model_config else None,
            "algorithm": run.model_config.algorithm if run.model_config else None,
            "metrics": slim_metrics(metrics) if slim else metrics,
        }

    metrics = json.loads(run.val_metrics_json or "{}")
    return {
        "run_id": run_id,
        "config_name": run.model_config.name if run.model_config else None,
        "algorithm": run.model_config.algorithm if run.model_config else None,
        "metrics": slim_metrics(metrics) if slim else metrics,
    }
