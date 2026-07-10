"""Transport-agnostic pagination envelope for ORM ``paginate()`` results.

Lives in ``services`` (not ``api.helpers``) so the read services can build the
standard list envelope without importing anything Flask-adjacent. The API layer
re-exports it from ``project.api.helpers`` for the routes that still shape
their own envelopes.
"""

from typing import Any


def pagination_envelope(items: list, paged) -> dict[str, Any]:
    """Standard ORM list envelope for a Flask-SQLAlchemy ``paginate()`` result.

    ``items`` is the (possibly enriched) serialised page; ``paged`` is the
    pagination object. Shape matches the pre-refactor hand-built dict exactly.
    """
    return {
        "items": items,
        "total": paged.total,
        "page": paged.page,
        "pages": paged.pages,
    }
