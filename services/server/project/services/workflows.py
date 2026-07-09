"""Workflow launch orchestration (transport-agnostic).

Shared by the Flask route and the future MCP "launch workflow" tool. No Flask
imports — the caller supplies the acting user's identity and a validated
``CreateWorkflow`` schema, and receives a plain dict (or raises a DomainError).
"""

import json
import re
import uuid
from datetime import datetime, timezone

from project import app_session
from project.constants import RunStatus, WorkflowStage
from project.core.calibration_launch import (
    build_search_config_json,
    validate_segmentation,
)
from project.db_models.calibration_models import CalibrationRun, Dataset, ModelConfig
from project.db_models.workflow_models import WorkflowRun
from project.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
)
from project.schemas.workflows import CreateWorkflow
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
    name, resolved_targets, analysis_params, datasets, identity, parsed_seg=None
):
    """Create a WorkflowRun + one CalibrationRun per target, then dispatch
    ``run_calibration`` for each. Returns ``(wf_dict, created_list)``.

    ``datasets`` = {'calibration', 'forecast', 'credit'|None, 'financial'|None}
    ``resolved_targets`` = [{'target_col', '_cfg': ModelConfig, 'feature_cols'}]
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


def create_workflow(payload: CreateWorkflow, identity: str) -> dict:
    """Validate the launch request against current datasets and launch it.

    Returns the workflow dict (with a ``targets`` list of created runs). Raises
    ``NotFoundError`` (404), ``BadRequestError`` (400) or
    ``UnprocessableEntityError`` (422) on invalid input.
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
    )
    wf_dict["targets"] = created_list
    return wf_dict


def rerun_workflow(run_id: str, identity: str) -> dict:
    """Relaunch an existing workflow from its stored targets/analysis params.

    Reuses the current latest datasets. Raises ``NotFoundError`` (404),
    ``ConflictError`` (409, still active) or ``UnprocessableEntityError`` (422).
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
        name, resolved_targets, analysis_params, datasets, identity
    )
    wf_dict["targets"] = created_list
    return wf_dict
