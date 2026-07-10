"""Calibration-run launch orchestration (transport-agnostic)."""

import json
import uuid

from project import app_session
from project.constants import RunStatus
from project.core.calibration_launch import (
    build_search_config_json,
    validate_segmentation,
)
from project.db_models.calibration_models import CalibrationRun, Dataset, ModelConfig
from project.exceptions import BadRequestError, NotFoundError
from project.schemas.calibrations import CreateCalibrationRun
from project.workers.tasks import run_calibration


def create_run(payload: CreateCalibrationRun, identity: str) -> dict:
    """Validate + create a CalibrationRun and dispatch ``run_calibration``.

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
