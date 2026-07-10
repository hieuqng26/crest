"""Request schemas for the credit-risk API / MCP tools."""

from pydantic import BaseModel, Field


class CreateCreditRiskRun(BaseModel):
    """Launch a credit-risk (KMV/ECL) analysis run.

    Typed ``exposure``/``discount_rate``/``lifetime_horizon`` mean a non-numeric
    value is a clean 400 (pydantic), not a 500 from an unguarded ``float()``.
    """

    dataset_id: int
    financial_portfolio_dataset_id: int | None = None
    # slot name -> forecast run uuid (e.g. {"total_assets": "<uuid>", ...})
    cal_inputs: dict[str, str] = Field(default_factory=dict)
    exposure: float = 1_000_000
    discount_rate: float = 0.05
    lifetime_horizon: int = 5
    curve: str = "moodys"
