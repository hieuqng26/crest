"""Shared Celery-task helpers (no task definitions, no cross-task dispatch).

Imported by every workers/<domain>.py module. Kept free of ``celery_app`` and of
any task import so it never participates in a task-dispatch import cycle.
"""

import json
import traceback
from datetime import datetime, timezone

import pandas as pd
from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler

from project.core import dataset_io
from project.logger import get_logger
from project.workers.context import worker_session

logger = get_logger(__name__)

_TRACEBACK_LIMIT = 20000


def format_failure(exc: BaseException, limit: int = _TRACEBACK_LIMIT) -> str:
    """Render the full traceback for persistence in a run's ``error_message``.

    The architecture contract is that a failed run keeps its traceback (not
    just ``str(exc)``) so failures are diagnosable from the run row alone. The
    tail is kept when the trace exceeds ``limit`` — the innermost frames (where
    the error actually occurred) are the most useful.
    """
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return tb[-limit:]


def _load_forecast_data(forecast) -> dict:
    """Load forecast payload — forecast_results rows for new runs, forecast_json fallback for old."""
    from project.db_models.calibration_models import ForecastResult

    # Fetch rows once and branch on the result — the old `results.count() > 0`
    # pre-check issued a second COUNT query on top of the same lazy relationship.
    rows = forecast.results.order_by(ForecastResult.id).all()
    if rows:
        actual = [r.actual for r in rows]
        predicted = [r.predicted for r in rows]
        client_id = [r.client_id for r in rows]
        date = [r.date for r in rows]
        meta_rows = [json.loads(r.meta_json or "{}") for r in rows]
        other_keys: set[str] = set()
        for m in meta_rows:
            other_keys.update(m.keys())
        meta: dict[str, list] = {k: [m.get(k) for m in meta_rows] for k in other_keys}
        if any(v is not None for v in client_id):
            meta["client_id"] = client_id
        if any(v is not None for v in date):
            meta["date"] = date
        return {"actual": actual, "predicted": predicted, "meta": meta}
    return json.loads(forecast.forecast_json or "{}")


logger = get_logger(__name__)


def _make_flask_app():
    from project import create_app

    return create_app()


def _get_scaler(name: str):
    return {
        "standard": StandardScaler(),
        "minmax": MinMaxScaler(),
        "robust": RobustScaler(),
    }.get(name)


def _split_segment_key(segment_key: str | None) -> tuple[str | None, str | None]:
    """Split a "{sector}__{split_value}" segment key into (sector, segment)."""
    if not segment_key or "__" not in segment_key:
        return None, None
    sector, split_value = segment_key.split("__", 1)
    return sector, split_value


def _cal_log(
    run_id: str,
    message: str,
    level: str = "info",
    sector: str | None = None,
    segment: str | None = None,
):
    """Write a CalibrationRunLog line WITHOUT touching the run's progress.

    Used for segment re-fits, which log against an already-complete parent run
    (progress 100) that must not be rewound. Silent-fails like _write_progress."""
    try:
        from project.db_models.calibration_models import CalibrationRunLog

        # worker_session() so this write never expires ORM objects the task holds.
        with worker_session() as s:
            s.add(
                CalibrationRunLog(
                    run_id=run_id,
                    logged_at=datetime.now(timezone.utc),
                    level=level,
                    message=message,
                    sector=sector,
                    segment=segment,
                )
            )
    except Exception as _e:
        logger.warning(f"_cal_log failed: {_e}")


def _write_progress(
    run_id: str,
    progress: int,
    message: str,
    sector: str | None = None,
    segment: str | None = None,
):
    """Write progress + a log line to DB. Always silent-fails so calibration is never blocked.

    ``sector``/``segment`` tag a segment-scoped line so the unified workflow log
    view can filter by them; leave them None for general lines."""
    try:
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunLog,
        )

        level = (
            "error"
            if progress < 0
            else ("warn" if "warn" in message.lower() else "info")
        )
        # worker_session() so this write never expires ORM objects the task holds.
        with worker_session() as s:
            r = s.query(CalibrationRun).filter_by(run_id=run_id).first()
            if r:
                r.progress = max(0, progress)
                r.progress_message = message
            s.add(
                CalibrationRunLog(
                    run_id=run_id,
                    logged_at=datetime.now(timezone.utc),
                    level=level,
                    message=message,
                    sector=sector,
                    segment=segment,
                )
            )
    except Exception:
        # Progress/log writes must never kill a run, but a silent failure hides
        # real DB problems — log it instead of swallowing outright.
        logger.exception("_write_progress failed for run %s", run_id)


def _write_forecast_progress(
    run_id: str,
    progress: int,
    message: str,
    level: str = "info",
    sector: str | None = None,
    segment: str | None = None,
):
    """Write progress + a log line for a forecast run. Silent-fails so the task is never blocked.

    ``sector``/``segment`` tag a segment-scoped line for the unified workflow log."""
    try:
        from project.db_models.forecast_models import ForecastRun, ForecastRunLog

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        # worker_session() so this write never expires ORM objects the task holds.
        with worker_session() as s:
            r = s.query(ForecastRun).filter_by(run_id=run_id).first()
            if r:
                r.progress = max(0, progress)
            s.add(
                ForecastRunLog(
                    run_id=run_id,
                    t=now,
                    level=level,
                    message=message,
                    sector=sector,
                    segment=segment,
                )
            )
    except Exception:
        # Progress/log writes must never kill a run, but a silent failure hides
        # real DB problems — log it instead of swallowing outright.
        logger.exception("_write_forecast_progress failed for run %s", run_id)


def _cr_log(
    cr_run_id: str,
    message: str,
    level: str = "info",
    progress: int | None = None,
    sector: str | None = None,
    segment: str | None = None,
):
    """Write a log line for a credit risk run. Silent-fails so the task is never blocked.

    ``sector``/``segment`` tag a segment-scoped line for the unified workflow log."""
    try:
        from project.db_models.credit_models import CreditRiskRun, CreditRiskRunLog

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        # worker_session() so this write never expires ORM objects the task holds.
        with worker_session() as s:
            s.add(
                CreditRiskRunLog(
                    run_id=cr_run_id,
                    t=now,
                    level=level,
                    message=message,
                    sector=sector,
                    segment=segment,
                )
            )
            if progress is not None:
                r = s.query(CreditRiskRun).filter_by(run_id=cr_run_id).first()
                if r:
                    r.progress = progress
    except Exception as _e:
        logger.warning(f"_cr_log failed: {_e}")


def _load_df_by_dataset_id(ds_id: int) -> "pd.DataFrame":
    """Download a dataset by PK and return its DataFrame (csv/xlsx/parquet)."""
    return dataset_io.load_dataset_df_by_id(ds_id)


SLOT_BY_TARGET = {
    "total_assets": "total_assets",
    "total_shortterm_debts": "short_term_debts",
    "total_longterm_debts": "long_term_debts",
    "total_revenue": "total_revenue",
    "total_cogs": "total_cogs",
}
# These slots must be present for credit analysis to run; revenue/cogs are optional
# (they enable heatmap metrics but the KMV/ECL computation doesn't require them).
REQUIRED_SLOTS = {"total_assets", "short_term_debts", "long_term_debts"}
