"""Flask extension singletons + the app-level DB session helper.

Kept separate from the app factory (``create_app`` in ``project/__init__``) so
that importing an extension (``db``, ``cache``, …) never risks pulling in the
blueprint/model imports that live inside the factory. ``project/__init__``
re-exports everything here, so ``from project import db`` keeps working.
"""

import os
from contextlib import contextmanager

from flask_bcrypt import Bcrypt
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
bcrypt = Bcrypt()
cache = Cache()

# Per-client-IP rate limiter (ProxyFix makes get_remote_address the real client
# IP). Storage/enabled come from config (Redis in dev/prod, disabled in tests);
# per-route limits are declared with @limiter.limit on the endpoints.
limiter = Limiter(key_func=get_remote_address)

DATA_STORE = os.getenv("DATA_STORE", "/var/lib/app_data")


@contextmanager
def app_session():
    """Transactional scope around the shared scoped ``db.session``.

    NOTE: closing the scoped session here expires every ORM instance bound to
    it. Celery tasks that hold objects across a progress write must use
    ``project.workers.context.worker_session`` instead — see
    .claude/bugs/detached-instance-in-celery-tasks.md.
    """
    try:
        yield db.session
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        db.session.close()
