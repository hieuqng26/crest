"""Session/app-context helpers for Celery tasks.

``worker_session()`` is the structural fix for the detached-instance bug class
(see .claude/bugs/detached-instance-in-celery-tasks.md): unlike ``app_session()``
— which closes the SHARED scoped ``db.session`` in its ``finally`` and thereby
expires *every* ORM instance a task is holding — this yields a fresh, independent
Session bound to the same engine. Closing it never touches ``db.session``, so a
progress/log write is safe to call while the task still holds objects loaded
from ``db.session``.

Anything querying/writing through ``worker_session`` must go through the yielded
session (``s.query(Model)`` / ``s.get(Model, pk)`` / ``s.add(obj)``) — the
``Model.query`` shortcut always binds to the scoped session, which would defeat
the isolation.
"""

from contextlib import contextmanager

from sqlalchemy.orm import Session

from project import db


@contextmanager
def worker_session():
    """Transactional scope on an independent Session (does not touch db.session)."""
    session = Session(db.engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
