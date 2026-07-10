"""Dataset reads (transport-agnostic).

Only the metadata listing lives here — upload/query/stats are transport-bound
(file streams, raw SQL) and stay route-resident, deliberately not MCP-exposed.
"""

from project.db_models.calibration_models import Dataset


def list_datasets(kind: str | None = None, limit: int | None = None) -> list[dict]:
    """Non-deleted datasets, newest first, optionally filtered by kind."""
    q = Dataset.query.filter(Dataset.status != "deleted")
    if kind:
        q = q.filter(Dataset.kind == kind)
    q = q.order_by(Dataset.created_at.desc())
    if limit is not None:
        q = q.limit(limit)
    return [r.to_dict() for r in q.all()]
