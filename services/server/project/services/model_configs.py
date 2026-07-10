"""Model-config reads (transport-agnostic).

CRUD stays route-resident (not MCP-exposed); the listing is shared by the
Flask route and the MCP ``crest_list_model_configs`` tool.
"""

from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunSegment,
    ModelConfig,
)


def _used_by_label(config_id: int) -> str:
    sectors = (
        CalibrationRunSegment.query.with_entities(CalibrationRunSegment.sector)
        .filter_by(model_config_id=config_id)
        .distinct()
        .count()
    )
    if sectors:
        return f"{sectors} sector{'s' if sectors != 1 else ''}"
    direct = CalibrationRun.query.filter_by(model_config_id=config_id).count()
    return f"{direct} run{'s' if direct != 1 else ''}" if direct else "—"


def list_configs(limit: int | None = None) -> list[dict]:
    """All saved model configurations, newest first, with a usage label."""
    q = ModelConfig.query.order_by(ModelConfig.created_at.desc())
    if limit is not None:
        q = q.limit(limit)
    result = []
    for r in q.all():
        d = r.to_dict()
        d["used_by"] = _used_by_label(r.id)
        result.append(d)
    return result
