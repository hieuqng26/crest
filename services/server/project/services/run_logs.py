"""Run-log reads for the three run domains (transport-agnostic).

One cursor-paginated read over the ``*_run_logs`` tables, shared by the Flask
log routes (via ``project.api.utils.paginate_logs``) and the MCP
``crest_get_run_logs`` tool. Progress/log rows are DB-persisted and polled —
there is no push channel (SocketIO was removed).
"""

from project.db_models.calibration_models import CalibrationRun, CalibrationRunLog
from project.db_models.credit_models import CreditRiskRun, CreditRiskRunLog
from project.db_models.forecast_models import ForecastRun, ForecastRunLog
from project.exceptions import BadRequestError, NotFoundError

RUN_LOG_MODELS = {
    "calibration": (CalibrationRun, CalibrationRunLog),
    "forecast": (ForecastRun, ForecastRunLog),
    "credit_risk": (CreditRiskRun, CreditRiskRunLog),
}


def paginate_log_query(base_query, id_col, after_id=None, limit=None, max_limit=5000):
    """Cursor-paginate a run-log query.

    Poll callers pass ``after_id`` (the id of the last row they already hold)
    and only the newer rows are returned — instead of re-sending the whole,
    ever-growing log table on every poll. Without a cursor the initial load
    returns the most recent ``limit`` rows (chronologically ordered), so a long
    run doesn't ship its entire history up front. Rows are always returned
    oldest→newest so the caller can append.
    """
    limit = max(1, min(limit or max_limit, max_limit))
    if after_id is not None:
        return (
            base_query.filter(id_col > after_id)
            .order_by(id_col.asc())
            .limit(limit)
            .all()
        )
    rows = base_query.order_by(id_col.desc()).limit(limit).all()
    rows.reverse()
    return rows


def get_logs(
    run_type: str,
    run_id: str,
    after_id: int | None = None,
    limit: int = 200,
    max_limit: int = 500,
) -> dict:
    """One cursor page of a run's log lines, oldest→newest within the page.

    Tail semantics: without ``after_id`` the MOST RECENT ``limit`` lines are
    returned (a long run doesn't ship its whole history up front); with
    ``after_id`` only lines newer than that id. Returns ``{"logs": [...],
    "next_after_id": int|None, "has_more": bool}`` — pass ``next_after_id``
    back as ``after_id`` to poll for fresh lines on a live run. Raises
    ``BadRequestError`` (unknown ``run_type``) / ``NotFoundError`` (404).
    """
    models = RUN_LOG_MODELS.get(run_type)
    if not models:
        raise BadRequestError(
            f"Unknown run_type '{run_type}' — expected one of {sorted(RUN_LOG_MODELS)}"
        )
    run_model, log_model = models
    if not run_model.query.filter_by(run_id=run_id).first():
        raise NotFoundError("Not found")

    limit = max(1, min(limit, max_limit))
    rows = paginate_log_query(
        log_model.query.filter_by(run_id=run_id),
        log_model.id,
        after_id=after_id,
        limit=limit,
        max_limit=max_limit,
    )
    logs = [r.to_dict() for r in rows]
    return {
        "logs": logs,
        "next_after_id": logs[-1]["id"] if logs else after_id,
        # A full page usually means more rows exist; an exact-boundary false
        # positive just costs the caller one empty follow-up read.
        "has_more": len(logs) == limit,
    }
