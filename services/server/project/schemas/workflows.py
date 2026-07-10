"""Request schemas for the workflows API / MCP tools."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkflowTarget(BaseModel):
    # protected_namespaces=() so the ``model_config_id`` field is allowed
    # (pydantic v2 reserves the ``model_`` prefix by default).
    model_config = ConfigDict(protected_namespaces=())

    target_col: str = Field(min_length=1)
    model_config_id: int | None = None  # per-target override of the default
    feature_cols: list[str] | None = None


class AnalysisParams(BaseModel):
    exposure: float = 1_000_000
    discount_rate: float = 0.05
    lifetime_horizon: int = 5
    curve: str = "moodys"


class CreateWorkflow(BaseModel):
    """Launch a multi-target train -> forecast -> credit-analysis workflow.

    Only request-shape validation lives here; dataset-dependent checks (target
    present/numeric in the calibration dataset, features present in the forecast
    dataset) run in the service and raise 422s, since they need DB state.
    """

    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(min_length=1)
    targets: list[WorkflowTarget] = Field(min_length=1)
    model_config_id: int  # default config for targets without an override
    feature_cols: list[str] | None = None  # default features for all targets
    segmentation: dict | None = None
    analysis: AnalysisParams = Field(default_factory=AnalysisParams)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name is required")
        return v

    @field_validator("targets")
    @classmethod
    def _unique_target_cols(cls, targets: list[WorkflowTarget]):
        cols = [t.target_col for t in targets]
        if len(set(cols)) != len(cols):
            raise ValueError("targets must have unique target_col values")
        return targets
