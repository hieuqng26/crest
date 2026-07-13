"""Workflow orchestration and reads (transport-agnostic).

Shared by the Flask routes and the MCP tools. No Flask imports — the caller
supplies the acting user's identity and validated arguments, and receives a
plain dict (or raises a DomainError).
"""

import json
import re
import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import selectinload

from project import app_session, db
from project.constants import LaunchOrigin, RunStatus, WorkflowStage
from project.core import table_query
from project.core.calibration_launch import (
    build_search_config_json,
    validate_segmentation,
)
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunLog,
    CalibrationRunSegment,
    Dataset,
    ModelConfig,
)
from project.db_models.credit_models import CreditRiskRun, CreditRiskRunLog
from project.db_models.forecast_models import ForecastRun, ForecastRunLog
from project.db_models.workflow_models import WorkflowRun
from project.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
)
from project.schemas.workflows import CreateWorkflow
from project.services._pagination import pagination_envelope
from project.workers.tasks import run_calibration

_NUMERIC_DTYPE_PREFIXES = ("int", "float", "uint")


def latest_dataset(kind: str) -> Dataset | None:
    """Most recently uploaded ready dataset of a given kind."""
    return (
        Dataset.query.filter_by(kind=kind, status="ready")
        .order_by(Dataset.created_at.desc())
        .first()
    )


def dataset_schema(ds: Dataset) -> tuple[set, dict]:
    schema = json.loads(ds.schema_json or "{}")
    return set(schema.get("columns", [])), schema.get("dtypes", {})


def launch_workflow(
    name,
    resolved_targets,
    analysis_params,
    datasets,
    identity,
    parsed_seg=None,
    origin: str = LaunchOrigin.MANUAL,
):
    """Create a WorkflowRun + one CalibrationRun per target, then dispatch
    ``run_calibration`` for each. Returns ``(wf_dict, created_list)``.

    ``datasets`` = {'calibration', 'forecast', 'credit'|None, 'financial'|None}
    ``resolved_targets`` = [{'target_col', '_cfg': ModelConfig, 'feature_cols'}]
    ``origin`` (MANUAL from HTTP wizard, AUTO from MCP) is stamped on the
    workflow and every child run so job history tags them consistently.
    """
    if parsed_seg is None:
        parsed_seg = {
            "seg_sectors_json": None,
            "seg_split_by": None,
            "seg_max_segments": None,
            "seg_sector_overrides_json": None,
        }

    cal_ds = datasets["calibration"]
    fc_ds = datasets["forecast"]
    credit_ds = datasets.get("credit")
    fin_ds = datasets.get("financial")

    wf_run_id = str(uuid.uuid4())

    with app_session() as s:
        wf = WorkflowRun(
            run_id=wf_run_id,
            name=name,
            status=RunStatus.QUEUED,
            current_stage=WorkflowStage.TRAINING,
            triggered_by=identity,
            origin=origin,
            created_at=datetime.now(timezone.utc),
            calibration_dataset_id=cal_ds.id,
            forecast_dataset_id=fc_ds.id,
            credit_dataset_id=credit_ds.id if credit_ds else None,
            financial_dataset_id=fin_ds.id if fin_ds else None,
            targets_json=json.dumps(
                [
                    {
                        "target_col": t["target_col"],
                        "model_config_id": t["_cfg"].id,
                        "feature_cols": t["feature_cols"],
                    }
                    for t in resolved_targets
                ]
            ),
            analysis_params_json=json.dumps(analysis_params),
        )
        s.add(wf)
        s.flush()

        created = []
        for t in resolved_targets:
            cfg = t["_cfg"]
            cal_run_id = str(uuid.uuid4())
            run = CalibrationRun(
                run_id=cal_run_id,
                name=f"{name} · {t['target_col']}",
                dataset_id=cal_ds.id,
                model_config_id=cfg.id,
                status=RunStatus.QUEUED,
                triggered_by=identity,
                origin=origin,
                search_config_json=build_search_config_json(cfg),
                train_split=cfg.train_split if cfg.train_split is not None else 0.8,
                scaler=cfg.scaler,
                target_col=t["target_col"],
                feature_cols_json=json.dumps(t["feature_cols"]),
                seg_sectors_json=parsed_seg["seg_sectors_json"],
                seg_split_by=parsed_seg["seg_split_by"],
                seg_max_segments=parsed_seg["seg_max_segments"],
                seg_sector_overrides_json=parsed_seg["seg_sector_overrides_json"],
                workflow_run_id=wf.id,
            )
            s.add(run)
            s.flush()
            created.append(
                {"target_col": t["target_col"], "calibration_run_id": cal_run_id}
            )

        wf_dict = wf.to_dict()

    # Dispatch after the session commits — if it had rolled back, these tasks
    # would reference non-existent rows.
    for c in created:
        run_calibration.delay(c["calibration_run_id"])

    return wf_dict, created


def _resolve_config(config_id: int, *, target_col: str | None = None) -> ModelConfig:
    cfg = ModelConfig.query.get(int(config_id))
    if cfg:
        return cfg
    if target_col:
        raise NotFoundError(
            f"ModelConfig {config_id} not found for target '{target_col}'"
        )
    raise NotFoundError("ModelConfig not found")


def create_workflow(
    payload: CreateWorkflow,
    identity: str,
    origin: str = LaunchOrigin.MANUAL,
) -> dict:
    """Validate the launch request against current datasets and launch it.

    ``origin`` (MANUAL from the HTTP wizard, AUTO from MCP) tags the workflow +
    children in job history. Returns the workflow dict (with a ``targets`` list
    of created runs). Raises ``NotFoundError`` (404), ``BadRequestError`` (400)
    or ``UnprocessableEntityError`` (422) on invalid input.
    """
    default_cfg = _resolve_config(payload.model_config_id)

    resolved_targets = []
    for t in payload.targets:
        cfg = (
            _resolve_config(t.model_config_id, target_col=t.target_col)
            if t.model_config_id
            else default_cfg
        )
        resolved_targets.append(
            {
                "target_col": t.target_col,
                "feature_cols": t.feature_cols or None,
                "_cfg": cfg,
            }
        )

    parsed_seg, seg_error = validate_segmentation(payload.segmentation or None)
    if seg_error:
        raise BadRequestError(seg_error)

    cal_ds = latest_dataset("calibration")
    if not cal_ds:
        raise UnprocessableEntityError(
            "No calibration dataset uploaded yet — upload a dataset of kind "
            "'calibration' first."
        )
    fc_ds = latest_dataset("forecast")
    if not fc_ds:
        raise UnprocessableEntityError(
            "No forecast dataset uploaded yet — upload a macro forecast dataset "
            "(kind 'forecast') first."
        )
    credit_ds = latest_dataset("credit")
    fin_ds = latest_dataset("financial_portfolio")

    cal_columns, cal_dtypes = dataset_schema(cal_ds)
    fc_columns, _ = dataset_schema(fc_ds)

    def _is_numeric(col: str) -> bool:
        return str(cal_dtypes.get(col, "")).startswith(_NUMERIC_DTYPE_PREFIXES)

    all_target_cols = {t["target_col"] for t in resolved_targets}
    default_feature_cols = payload.feature_cols or None

    for t in resolved_targets:
        if t["target_col"] not in cal_columns:
            raise UnprocessableEntityError(
                f"target_col '{t['target_col']}' not found in the calibration dataset"
            )
        if not _is_numeric(t["target_col"]):
            raise UnprocessableEntityError(
                f"target_col '{t['target_col']}' is not numeric in the calibration "
                "dataset"
            )

    def _default_features_for(target_col: str) -> list:
        return sorted(
            c
            for c in cal_columns
            if _is_numeric(c) and c not in all_target_cols and c in fc_columns
        )

    for t in resolved_targets:
        feats = (
            t["feature_cols"]
            or default_feature_cols
            or _default_features_for(t["target_col"])
        )
        # Leakage guard: a target can never be used as a sibling's feature.
        feats = [f for f in feats if f not in all_target_cols]
        missing_in_forecast = sorted(set(feats) - fc_columns)
        if missing_in_forecast:
            raise UnprocessableEntityError(
                f"Feature column(s) {missing_in_forecast} for target "
                f"'{t['target_col']}' are not present in the forecast dataset — the "
                "forecast stage would fail. Remove them or pick different features."
            )
        t["feature_cols"] = feats

    analysis_params = {
        "exposure": float(payload.analysis.exposure),
        "discount_rate": float(payload.analysis.discount_rate),
        "lifetime_horizon": int(payload.analysis.lifetime_horizon),
        "curve": payload.analysis.curve,
    }

    datasets = {
        "calibration": cal_ds,
        "forecast": fc_ds,
        "credit": credit_ds,
        "financial": fin_ds,
    }
    wf_dict, created_list = launch_workflow(
        payload.name,
        resolved_targets,
        analysis_params,
        datasets,
        identity,
        parsed_seg,
        origin=origin,
    )
    wf_dict["targets"] = created_list
    return wf_dict


def _original_segmentation(workflow_pk: int) -> dict | None:
    """Recover a workflow's segmentation config from its child calibration runs.

    Segmentation is persisted per ``CalibrationRun`` (WorkflowRun has no seg
    columns) and a workflow applies one uniform config to every target, so the
    first segmented child carries it. Returns ``None`` for a non-segmented
    workflow (``launch_workflow`` then defaults to no segmentation) — without
    this, a re-run would silently drop segmentation and lose every downstream
    sector/segment view (logs, forecast, diagnostics, credit).
    """
    child = (
        CalibrationRun.query.filter(
            CalibrationRun.workflow_run_id == workflow_pk,
            CalibrationRun.seg_sectors_json.isnot(None),
        )
        .order_by(CalibrationRun.id.asc())
        .first()
    )
    if not child:
        return None
    return {
        "seg_sectors_json": child.seg_sectors_json,
        "seg_split_by": child.seg_split_by,
        "seg_max_segments": child.seg_max_segments,
        "seg_sector_overrides_json": child.seg_sector_overrides_json,
    }


def rerun_workflow(
    run_id: str,
    identity: str,
    origin: str = LaunchOrigin.MANUAL,
) -> dict:
    """Relaunch an existing workflow from its stored targets/analysis params.

    ``origin`` reflects who launched the RE-RUN (MANUAL from HTTP, AUTO from
    MCP), not the original. Reuses the current latest datasets. Raises
    ``NotFoundError`` (404), ``ConflictError`` (409, still active) or
    ``UnprocessableEntityError`` (422).
    """
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        raise NotFoundError("Not found")
    if wf.status in (RunStatus.QUEUED, RunStatus.RUNNING):
        raise ConflictError("Workflow is still active — cancel it before re-running")

    targets_raw = json.loads(wf.targets_json or "[]")
    resolved_targets = []
    for t in targets_raw:
        cfg = ModelConfig.query.get(t["model_config_id"])
        if not cfg:
            raise UnprocessableEntityError(
                f"ModelConfig {t['model_config_id']} not found for target "
                f"'{t['target_col']}' — configuration may have been deleted"
            )
        resolved_targets.append(
            {
                "target_col": t["target_col"],
                "feature_cols": t.get("feature_cols") or [],
                "_cfg": cfg,
            }
        )

    cal_ds = latest_dataset("calibration")
    if not cal_ds:
        raise UnprocessableEntityError(
            "No calibration dataset uploaded yet — upload a dataset of kind "
            "'calibration' first."
        )
    fc_ds = latest_dataset("forecast")
    if not fc_ds:
        raise UnprocessableEntityError(
            "No forecast dataset uploaded yet — upload a macro forecast dataset "
            "(kind 'forecast') first."
        )

    datasets = {
        "calibration": cal_ds,
        "forecast": fc_ds,
        "credit": latest_dataset("credit"),
        "financial": latest_dataset("financial_portfolio"),
    }
    analysis_params = json.loads(wf.analysis_params_json or "{}")
    name = re.sub(r"( \(re-run\))+$", "", wf.name) + " (re-run)"
    wf_dict, created_list = launch_workflow(
        name,
        resolved_targets,
        analysis_params,
        datasets,
        identity,
        _original_segmentation(wf.id),
        origin=origin,
    )
    wf_dict["targets"] = created_list
    return wf_dict


def list_workflows(page: int = 1, per_page: int = 50) -> dict:
    """Paginated workflow list, newest first. Each workflow is one process with
    a single overall status — no per-stage breakdown here; see ``get_workflow``
    for the per-target detail."""
    paged = WorkflowRun.query.order_by(WorkflowRun.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    wf_ids = [wf.id for wf in paged.items]
    cr_by_wf = {}
    if wf_ids:
        for cr in CreditRiskRun.query.filter(
            CreditRiskRun.workflow_run_id.in_(wf_ids)
        ).all():
            cr_by_wf[cr.workflow_run_id] = cr

    result = []
    for wf in paged.items:
        d = wf.to_dict()
        cr = cr_by_wf.get(wf.id)
        d["analysis_summary"] = (
            {"run_id": cr.run_id, "is_active": bool(cr.is_active), "status": cr.status}
            if cr
            else None
        )
        result.append(d)
    return pagination_envelope(result, paged)


def _retraining_counts(cal_ids):
    """Segments queued/running per calibration, in one grouped query.

    A segment re-run leaves the parent run's status at "success", so this count
    is the only signal the UI has to surface a per-target "Retraining" state.
    """
    if not cal_ids:
        return {}
    rows = (
        db.session.query(
            CalibrationRunSegment.calibration_run_id,
            db.func.count(CalibrationRunSegment.id),
        )
        .filter(
            CalibrationRunSegment.calibration_run_id.in_(cal_ids),
            CalibrationRunSegment.status.in_(("queued", "running")),
        )
        .group_by(CalibrationRunSegment.calibration_run_id)
        .all()
    )
    return dict(rows)


def _get_workflow_light(wf: WorkflowRun) -> dict:
    """Status-only workflow payload for the 5s poll.

    Returns just the fields the page needs to stay live — per-target statuses,
    progress and the retraining count — without the heavy per-run to_dict()
    (which serialises train_metrics_json / val_metrics_json blobs) or the
    dataset-name lookups. The frontend merges this into the full object it
    already holds, so the static fields it omits are preserved.
    """
    cals = CalibrationRun.query.filter_by(workflow_run_id=wf.id).all()
    fcs = ForecastRun.query.filter_by(workflow_run_id=wf.id).all()
    crs = CreditRiskRun.query.filter_by(workflow_run_id=wf.id).first()
    fcs_by_cal = {fr.calibration_run_id: fr for fr in fcs}
    retraining_by_cal = _retraining_counts([c.id for c in cals])

    targets = []
    for cal in cals:
        fr = fcs_by_cal.get(cal.id)
        targets.append(
            {
                "target_col": cal.target_col,
                "calibration": {
                    "run_id": cal.run_id,
                    "status": cal.status,
                    "progress": cal.progress,
                    "finished_at": cal.finished_at.isoformat()
                    if cal.finished_at
                    else None,
                    "retraining_segment_count": retraining_by_cal.get(cal.id, 0),
                },
                "forecast": {
                    "run_id": fr.run_id,
                    "status": fr.status,
                    "progress": fr.progress,
                    "finished_at": fr.finished_at.isoformat()
                    if fr.finished_at
                    else None,
                }
                if fr
                else None,
            }
        )

    return {
        "run_id": wf.run_id,
        "status": wf.status,
        "current_stage": wf.current_stage,
        "finished_at": wf.finished_at.isoformat() if wf.finished_at else None,
        "error_message": wf.error_message,
        "targets": targets,
        "analysis": {
            "run_id": crs.run_id,
            "status": crs.status,
            "progress": crs.progress,
            "finished_at": crs.finished_at.isoformat() if crs.finished_at else None,
        }
        if crs
        else None,
    }


def get_workflow(run_id: str, light: bool = False) -> dict:
    """One workflow with per-target calibration/forecast detail.

    ``light=True`` returns the status-only polling payload. Raises
    ``NotFoundError`` (404).
    """
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        raise NotFoundError("Not found")

    if light:
        return _get_workflow_light(wf)

    cals = (
        CalibrationRun.query.options(selectinload(CalibrationRun.model_config))
        .filter_by(workflow_run_id=wf.id)
        .all()
    )
    fcs = ForecastRun.query.filter_by(workflow_run_id=wf.id).all()
    crs = CreditRiskRun.query.filter_by(workflow_run_id=wf.id).all()
    fcs_by_cal = {fr.calibration_run_id: fr for fr in fcs}
    cal_by_id = {cal.id: cal for cal in cals}

    # Batch-load every dataset referenced by the forecast runs and by the four
    # workflow dataset slots, so the per-target fr.to_dict() and the slot loop
    # below don't each fire their own .get() (was 3 queries/target + 4 slot gets).
    ds_ids = {fr.dataset_id for fr in fcs}
    ds_ids.update(
        i
        for i in (
            wf.calibration_dataset_id,
            wf.forecast_dataset_id,
            wf.credit_dataset_id,
            wf.financial_dataset_id,
        )
        if i
    )
    datasets = (
        {d.id: d for d in Dataset.query.filter(Dataset.id.in_(ds_ids))}
        if ds_ids
        else {}
    )

    retraining_by_cal = _retraining_counts([c.id for c in cals])

    targets = []
    for cal in cals:
        cal_d = cal.to_dict()
        cal_d["retraining_segment_count"] = retraining_by_cal.get(cal.id, 0)
        cal_d["config_name"] = cal.model_config.name if cal.model_config else None
        cal_d["algorithm"] = cal.model_config.algorithm if cal.model_config else None
        fr = fcs_by_cal.get(cal.id)
        forecast_d = None
        if fr:
            fr_cal = cal_by_id.get(fr.calibration_run_id)
            fr_cfg = fr_cal.model_config if fr_cal else None
            forecast_d = fr.to_dict(
                cal_run=fr_cal,
                dataset=datasets.get(fr.dataset_id),
                config_name=fr_cfg.name if fr_cfg else None,
            )
        targets.append(
            {
                "target_col": cal.target_col,
                "calibration": cal_d,
                "forecast": forecast_d,
            }
        )

    d = wf.to_dict()
    d["targets"] = targets
    d["analysis"] = crs[0].to_dict() if crs else None
    for key, ds_id in (
        ("calibration_dataset_name", wf.calibration_dataset_id),
        ("forecast_dataset_name", wf.forecast_dataset_id),
        ("credit_dataset_name", wf.credit_dataset_id),
        ("financial_dataset_name", wf.financial_dataset_id),
    ):
        ds = datasets.get(ds_id) if ds_id else None
        d[key] = ds.name if ds else None
    return d


# ── Unified workflow logs ───────────────────────────────────────────────────────
# One paginated/filterable view over the workflow's training + forecast + credit
# log lines, each tagged with step/target/sector/segment so the Overview log panel
# can filter without hitting three separate endpoints.

_LOG_STEP_RANK = {"Training": 0, "Forecast": 1, "Credit": 2}
_LOG_COLUMNS = ["step", "target", "sector", "segment", "t", "level", "message"]


def workflow_log_df(wf: WorkflowRun) -> pd.DataFrame:
    """Every training/forecast/credit log line of a workflow as one tagged frame."""
    cals = CalibrationRun.query.filter_by(workflow_run_id=wf.id).all()
    cal_target = {c.run_id: c.target_col for c in cals}
    cal_uuid_by_id = {c.id: c.run_id for c in cals}
    fcs = ForecastRun.query.filter_by(workflow_run_id=wf.id).all()
    fr_target = {
        fr.run_id: cal_target.get(cal_uuid_by_id.get(fr.calibration_run_id))
        for fr in fcs
    }
    crs = CreditRiskRun.query.filter_by(workflow_run_id=wf.id).all()

    records: list[dict] = []
    if cal_target:
        for log in CalibrationRunLog.query.filter(
            CalibrationRunLog.run_id.in_(list(cal_target))
        ).all():
            records.append(
                {
                    "step": "Training",
                    "target": cal_target.get(log.run_id),
                    "sector": log.sector,
                    "segment": log.segment,
                    # Full UTC datetime (matching ForecastRunLog/CreditRiskRunLog.t
                    # and CalibrationRunLog.to_dict); the client renders it in the
                    # configured display timezone via fmtTime, so all log rows and
                    # the run-details chips agree on time.
                    "t": log.logged_at.strftime("%Y-%m-%d %H:%M:%S")
                    if log.logged_at
                    else None,
                    "level": log.level,
                    "message": log.message,
                    "_id": log.id,
                }
            )
    if fcs:
        for log in ForecastRunLog.query.filter(
            ForecastRunLog.run_id.in_([fr.run_id for fr in fcs])
        ).all():
            records.append(
                {
                    "step": "Forecast",
                    "target": fr_target.get(log.run_id),
                    "sector": log.sector,
                    "segment": log.segment,
                    "t": log.t,
                    "level": log.level,
                    "message": log.message,
                    "_id": log.id,
                }
            )
    if crs:
        for log in CreditRiskRunLog.query.filter(
            CreditRiskRunLog.run_id.in_([cr.run_id for cr in crs])
        ).all():
            records.append(
                {
                    "step": "Credit",
                    "target": None,
                    "sector": log.sector,
                    "segment": log.segment,
                    "t": log.t,
                    "level": log.level,
                    "message": log.message,
                    "_id": log.id,
                }
            )

    df = pd.DataFrame.from_records(records, columns=[*_LOG_COLUMNS, "_id"])
    if df.empty:
        return df[_LOG_COLUMNS]
    # Default order is reverse-chronological by the workflow's execution order:
    # Credit (last stage) → Forecast → Training, newest id first within each stage.
    df["_rank"] = df["step"].map(_LOG_STEP_RANK).fillna(99)
    df = df.sort_values(["_rank", "_id"], ascending=[False, False], kind="stable")
    return df[_LOG_COLUMNS]


def get_workflow_logs(
    run_id: str,
    page: int = 0,
    page_size: int = 50,
    sort_column: str | None = None,
    sort_order: str | None = None,
    filters: list | None = None,
) -> dict:
    """One filtered/sorted page of a workflow's unified log lines.

    ``filters`` is the already-parsed ``table_query`` filter list. Raises
    ``NotFoundError`` (404).
    """
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        raise NotFoundError("Not found")
    df = workflow_log_df(wf)
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


# ── Combined forecast results ───────────────────────────────────────────────────
# Every target's forecast run unioned into one table with derived
# target/sector/segment columns, so the Forecast tab shows all targets at once and
# the workflow export builds a single forecast-results file. Column order below.

FORECAST_COL_ORDER = ["target", "sector", "segment", "date", "predicted"]


def _seg_part(segment_key, idx):
    """sector (idx 0) or split value (idx 1) from a "{sector}__{split}" key."""
    if not isinstance(segment_key, str) or "__" not in segment_key:
        return segment_key if idx == 0 and isinstance(segment_key, str) else None
    return segment_key.split("__", 1)[idx]


def combined_forecast_df(wf: WorkflowRun) -> pd.DataFrame:
    """Union every target's forecast-run results into one frame with derived
    ``target``/``sector``/``segment`` columns. Empty frame with the canonical
    columns when the workflow has no forecast rows yet."""
    from project.services.forecast_runs import results_df as _forecast_results_df

    fcs = ForecastRun.query.filter_by(workflow_run_id=wf.id).all()
    cal_ids = {fr.calibration_run_id for fr in fcs}
    cal_target = (
        {
            c.id: c.target_col
            for c in CalibrationRun.query.filter(CalibrationRun.id.in_(cal_ids)).all()
        }
        if cal_ids
        else {}
    )

    frames = []
    for fr in fcs:
        df = _forecast_results_df(fr)
        if df.empty:
            continue
        df = df.copy()
        df.insert(0, "target", cal_target.get(fr.calibration_run_id))
        if "segment_key" in df.columns:
            sk = df["segment_key"].astype("object")
            derived_sector = sk.map(lambda v: _seg_part(v, 0))
            df["segment"] = sk.map(lambda v: _seg_part(v, 1))
            df["sector"] = (
                derived_sector.where(sk.notna(), df.get("sector"))
                if "sector" in df.columns
                else derived_sector
            )
            df = df.drop(columns=["segment_key"])
        else:
            if "sector" not in df.columns:
                df["sector"] = None
            df["segment"] = None
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=FORECAST_COL_ORDER)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    front = [c for c in FORECAST_COL_ORDER if c in combined.columns]
    rest = [c for c in combined.columns if c not in front]
    return combined[front + rest]
