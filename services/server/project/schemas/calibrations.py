"""Request schemas for the calibrations API / MCP tools."""

from pydantic import BaseModel, ConfigDict, Field


class CreateCalibrationRun(BaseModel):
    """Launch a single calibration run for a dataset + model config."""

    model_config = ConfigDict(protected_namespaces=())

    dataset_id: int
    model_config_id: int
    target_col: str | None = None
    feature_cols: list[str] = Field(default_factory=list)
    name: str | None = None
    segmentation: dict | None = None
