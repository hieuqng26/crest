"""Regression tests for the detached-instance fix (worker_session).

Before the fix, a progress/log writer opened app_session() which closed the
shared scoped db.session and expired every ORM object the task held — so reading
an attribute of a previously-loaded row afterwards raised DetachedInstanceError
(see .claude/bugs/detached-instance-in-celery-tasks.md). worker_session() writes
on an independent session, so held objects survive.

Run from services/server/:
    pytest tests/workers/test_worker_session.py -v
"""


def _make_calibration_run(run_id="ws-run-1", progress=5):
    from project import db
    from project.db_models.calibration_models import CalibrationRun

    run = CalibrationRun(
        run_id=run_id,
        status="running",
        target_col="total_assets",
        dataset_id=1,
        model_config_id=1,
        triggered_by="tester@example.com",
        progress=progress,
    )
    db.session.add(run)
    db.session.commit()
    return run


def test_write_progress_does_not_detach_held_instance(app):
    from project import db
    from project.db_models.calibration_models import CalibrationRun
    from project.workers.tasks import _write_progress

    run = _make_calibration_run()

    # Hold the ORM object, then do a progress write mid-"task".
    _write_progress(run.run_id, 50, "halfway")

    # Pre-fix this raised DetachedInstanceError; now the held object is intact.
    assert run.target_col == "total_assets"
    assert run.run_id == "ws-run-1"

    # The write really landed. A poller reads via its own session; expire the
    # scoped identity map so this assertion re-reads from the DB rather than the
    # cached (stale) instance.
    db.session.expire_all()
    refreshed = CalibrationRun.query.filter_by(run_id="ws-run-1").first()
    assert refreshed.progress == 50
    assert refreshed.progress_message == "halfway"


def test_cr_log_progress_write_visible(app):
    from project import db
    from project.db_models.credit_models import CreditRiskRun
    from project.workers.tasks import _cr_log

    cr = CreditRiskRun(
        run_id="ws-cr-1",
        status="running",
        dataset_id=1,
        exposure=1000.0,
        progress=0,
    )
    db.session.add(cr)
    db.session.commit()

    _cr_log("ws-cr-1", "step done", progress=42)

    # held object survives the write...
    assert cr.run_id == "ws-cr-1"
    # ...and the progress update is persisted.
    db.session.expire_all()
    refreshed = CreditRiskRun.query.filter_by(run_id="ws-cr-1").first()
    assert refreshed.progress == 42
