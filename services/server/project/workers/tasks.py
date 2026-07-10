"""Celery task registry — thin shim.

The task bodies live in per-domain modules (calibration/forecast/credit/segments/
workflow) with shared helpers in ``common``. This module re-exports them so that
``include=["project.workers.tasks"]`` still registers every task, and existing
``from project.workers.tasks import <name>`` imports (routes, services, tests)
keep working unchanged.

Note on patching: patching a *task object's* attribute (e.g.
``project.workers.tasks.run_forecast.delay``) works from here because it mutates
the shared task object. Patching a *plain function name* the tasks call
internally (``_make_flask_app``, ``storage``) must target the module that runs
it (e.g. ``project.workers.calibration._make_flask_app``), not this shim.

``celery_app`` is re-exported too, so the worker's
``-A project.workers.tasks.celery_app`` entrypoint keeps resolving.
"""

from project.workers import celery_app
from project.workers.calibration import (
    run_calibration,
    run_segment_calibration,
)
from project.workers.common import (
    _cr_log,
    _load_forecast_data,
    _make_flask_app,
    _write_progress,
    format_failure,
)
from project.workers.credit import (
    _compute_credit_for_clients,
    backfill_analysis_series,
    run_credit_analysis,
)
from project.workers.forecast import (
    recompute_forecast_run_segment,
    run_forecast,
)
from project.workers.segments import recompute_segment_downstream
from project.workers.workflow import (
    advance_workflow,
    advance_workflow_impl,
    delete_workflow,
)

__all__ = [
    "_compute_credit_for_clients",
    "_cr_log",
    "_load_forecast_data",
    "_make_flask_app",
    "_write_progress",
    "advance_workflow",
    "advance_workflow_impl",
    "backfill_analysis_series",
    "celery_app",
    "delete_workflow",
    "format_failure",
    "recompute_forecast_run_segment",
    "recompute_segment_downstream",
    "run_calibration",
    "run_credit_analysis",
    "run_forecast",
    "run_segment_calibration",
]
