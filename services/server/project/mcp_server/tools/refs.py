"""Reference reads: everything needed to construct a launch payload."""

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from project.mcp_server.runtime import tool_boundary
from project.mcp_server.server import mcp
from project.services import credit_risk as credit_risk_service
from project.services import datasets as dataset_service
from project.services import model_configs as model_config_service
from project.services import workflows as workflow_service

_READ = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

Limit = Annotated[int, Field(ge=1, le=100, description="Max items (newest first)")]

_WORKFLOW_DATASET_KINDS = ("calibration", "forecast", "credit", "financial_portfolio")


@mcp.tool(name="crest_list_datasets", annotations=_READ)
@tool_boundary
def crest_list_datasets(kind: str | None = None, limit: Limit = 50) -> list[dict]:
    """Uploaded datasets (id, name, kind, status, schema), newest first. kind:
    calibration | forecast | credit | financial_portfolio. Launch payloads
    reference datasets by their integer id."""
    return dataset_service.list_datasets(kind=kind, limit=limit)


@mcp.tool(name="crest_list_model_configs", annotations=_READ)
@tool_boundary
def crest_list_model_configs(limit: Limit = 50) -> list[dict]:
    """Saved model configurations (id, name, algorithm, family, hyperparams,
    train_split, usage label), newest first. Launch payloads reference configs
    by their integer id."""
    return model_config_service.list_configs(limit=limit)


@mcp.tool(name="crest_get_model_registry", annotations=_READ)
@tool_boundary
def crest_get_model_registry() -> list[dict]:
    """The plugin registry: every available algorithm with its family
    (regression/classification/timeseries) and hyperparameter schema — what a
    model config's `algorithm` and `hyperparams` may contain."""
    from project.core.model_registry import registry_metadata

    return registry_metadata()


@mcp.tool(name="crest_list_pd_ratings", annotations=_READ)
@tool_boundary
def crest_list_pd_ratings(curve: str = "moodys") -> list[dict]:
    """The rating→PD mapping table for one curve (used by KMV to map
    distance-to-default to a rating and LGD)."""
    return credit_risk_service.list_pd_ratings(curve)


@mcp.tool(name="crest_resolve_workflow_datasets", annotations=_READ)
@tool_boundary
def crest_resolve_workflow_datasets() -> dict:
    """The dataset each workflow slot would use right now: the newest ready
    upload per kind (calibration, forecast, credit, financial_portfolio); null
    where none is uploaded. calibration + forecast are required to launch a
    workflow."""
    return {
        kind: (ds.to_dict() if ds else None)
        for kind in _WORKFLOW_DATASET_KINDS
        for ds in [workflow_service.latest_dataset(kind)]
    }
