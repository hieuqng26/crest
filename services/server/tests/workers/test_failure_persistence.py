"""Regression tests for task failure handling.

The architecture contract (CLAUDE.md / architecture.md) is that a failed run
keeps its *full traceback* in ``error_message``, not just ``str(exc)``. These
tests exercise the real Celery task bodies (eagerly, against the test DB) and
assert the persisted error_message is a traceback.

Run from services/server/:
    pytest tests/workers/test_failure_persistence.py -v
"""

from unittest.mock import patch

import pytest


def test_format_failure_returns_full_traceback():
    from project.workers.tasks import format_failure

    def _boom():
        raise ValueError("kaboom")

    try:
        _boom()
    except ValueError as exc:
        rendered = format_failure(exc)

    assert "Traceback (most recent call last)" in rendered
    assert "ValueError: kaboom" in rendered
    assert "_boom" in rendered  # the offending frame is captured


def test_format_failure_keeps_tail_when_over_limit():
    from project.workers.tasks import format_failure

    try:
        raise RuntimeError("x" * 100)
    except RuntimeError as exc:
        full = format_failure(exc, limit=10_000)
        clipped = format_failure(exc, limit=40)

    assert len(clipped) == 40
    # the innermost frames (the tail) are what we keep
    assert clipped == full[-40:]


@pytest.fixture()
def use_test_app(app):
    """Make the task bodies run against the test app/DB instead of building a
    fresh app (with a separate in-memory SQLite) via create_app().

    Each task module binds its own ``_make_flask_app`` (imported from
    workers.common), and the task resolves that module-global at call time — so
    the patch must target the module the task lives in, not the tasks shim."""
    import contextlib

    modules = ("calibration", "forecast", "credit", "segments", "workflow")
    with contextlib.ExitStack() as stack:
        for mod in modules:
            stack.enter_context(
                patch(f"project.workers.{mod}._make_flask_app", return_value=app)
            )
        yield app


def test_run_calibration_persists_traceback_on_failure(use_test_app):
    from project import db
    from project.db_models.calibration_models import CalibrationRun
    from project.workers.tasks import run_calibration

    run = CalibrationRun(
        run_id="fail-cal-1",
        status="queued",
        target_col="total_assets",
        dataset_id=999999,  # no such dataset
        model_config_id=999999,  # no such config -> cfg.family raises
        triggered_by="tester@example.com",
    )
    db.session.add(run)
    db.session.commit()

    # Eager execution; the task re-raises after persisting, so the EagerResult
    # is a failure — we assert on the DB row, not the result.
    run_calibration.apply(args=["fail-cal-1"])

    row = CalibrationRun.query.filter_by(run_id="fail-cal-1").first()
    assert row.status == "failed"
    assert row.error_message is not None
    assert "Traceback (most recent call last)" in row.error_message


def test_run_credit_analysis_persists_traceback_on_failure(use_test_app):
    from project import db
    from project.db_models.credit_models import CreditRiskRun
    from project.workers.tasks import run_credit_analysis

    cr = CreditRiskRun(
        run_id="fail-cr-1",
        status="queued",
        dataset_id=999999,  # missing dataset -> failure inside the task body
        exposure=1000.0,
    )
    db.session.add(cr)
    db.session.commit()

    run_credit_analysis.apply(args=["fail-cr-1"])

    row = CreditRiskRun.query.filter_by(run_id="fail-cr-1").first()
    assert row.status == "failed"
    assert row.error_message is not None
    assert "Traceback (most recent call last)" in row.error_message
