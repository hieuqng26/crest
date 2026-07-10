"""Request schemas for the forecast-runs API / MCP tools."""

from pydantic import BaseModel, Field


class CreateForecastRun(BaseModel):
    """Launch a forecast for a completed calibration run against a dataset."""

    calibration_run_id: str = Field(min_length=1)
    dataset_id: int
    segment_key: str | None = None
    name: str | None = None
