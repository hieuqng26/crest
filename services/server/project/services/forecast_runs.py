"""Forecast-run launch orchestration (transport-agnostic)."""

import uuid
from datetime import datetime, timezone

from project import app_session
from project.constants import RunStatus
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunSegment,
    Dataset,
)
from project.db_models.forecast_models import ForecastRun
from project.exceptions import BadRequestError, NotFoundError
from project.schemas.forecast_runs import CreateForecastRun
from project.workers.tasks import run_forecast


def create_run(payload: CreateForecastRun, identity: str) -> dict:
    """Validate + create a ForecastRun and dispatch ``run_forecast``.

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
            created_at=datetime.now(timezone.utc),
            progress=0,
        )
        s.add(fr)
        s.flush()
        fr_dict = fr.to_dict()

    run_forecast.delay(run_id)
    return fr_dict
