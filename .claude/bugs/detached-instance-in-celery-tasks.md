# Bug: DetachedInstanceError on ORM objects inside Celery task functions

**Symptom:** `sqlalchemy.orm.exc.DetachedInstanceError: Instance <Model at 0x...>
is not bound to a Session; attribute refresh operation cannot proceed`, raised when
reading an attribute of an ORM object loaded earlier in the same task function.

**Cause:** `app_session()` (`project/__init__.py`) calls `db.session.close()` in its
`finally` block, which **expires every ORM instance** tied to the shared scoped
session — not just ones created inside that `with` block. Helper functions used for
progress/logging (`_write_forecast_progress`, `_cr_log`, etc.) each open their own
`with app_session() as s: ...`. If a task does:

```python
seg = CalibrationRunSegment.query.filter_by(...).first()
_write_forecast_progress(run_id, 45, "...")   # closes db.session — expires `seg`
predicted = model.predict(seg.artifact_path)   # DetachedInstanceError
```

the attribute read after the helper call fails because the session backing `seg` is
gone. This bit `run_forecast`'s segmented-calibration branches twice: once in the
original `elif is_segmented:` sector-routing code, and again when it was rewritten to
score every segment (`services/server/project/workers/tasks.py`, `_score_segment`
call sites) — the rewrite dropped the "extract scalars immediately" guard the
original code had.

**Fix:** Immediately after any query, pull every attribute you'll need into plain
values (str/int/tuple/dict) *before* calling any function that might touch
`app_session()` (progress writers, loggers, `s.add()` elsewhere). Never hold an ORM
object across such a call and read its attributes afterward.

```python
segments = CalibrationRunSegment.query.filter_by(...).all()
segment_refs = [(s.artifact_path, s.segment_key) for s in segments]  # extract now
_write_forecast_progress(run_id, 35, "...")  # safe — no ORM objects held
for seg_artifact_path, seg_key in segment_refs:
    ...
```

**Prevention:** In any Celery task under `project/workers/tasks.py`, treat
`_write_forecast_progress`, `_cr_log`, and any other helper wrapping `app_session()`
as a session-closing boundary. Query → extract scalars → then call the helper. This
mirrors the pattern already used at the top of `run_forecast`/`run_credit_analysis`
for loading initial run values before the main `try:` block.
