"""Unit tests for the pure credit-analysis read builders.

No DB/app needed — build_heatmap/build_forecast operate on a plain ``series``
dict, which is exactly how the MCP analysis-read tools will call them.

Run from services/server/:
    pytest tests/services/test_credit_analysis.py -v
"""

import pytest

from project.exceptions import (
    BadRequestError,
    NotFoundError,
    UnprocessableEntityError,
)
from project.services import credit_analysis as ca


def _revenue_series():
    return {
        "sector": {
            "Tech": {
                "total_revenue": {
                    ca.SERIES_HISTORY: {2020: 100.0, 2021: 110.0},
                    "Baseline": {2022: 121.0, 2023: 133.0},
                }
            }
        }
    }


def test_build_heatmap_revenue_growth_yoy():
    series = _revenue_series()
    payload = ca.build_heatmap(
        series,
        sector_of={},
        slots={"total_revenue": object()},
        metric="revenue_growth",
        sector_filter=None,
        client_filter=None,
        requested_scenario=None,
    )
    assert payload["metric"] == "revenue_growth"
    assert payload["scenario"] == "Baseline"
    assert payload["years"] == [2022, 2023]
    assert payload["rows"][0]["key"] == "Tech"
    # 2022: (121-110)/110*100 = 10.0 ; 2023: (133-121)/121*100 ≈ 9.9
    assert payload["rows"][0]["values"] == [10.0, 9.9]


def test_build_heatmap_unknown_metric_raises():
    with pytest.raises(BadRequestError):
        ca.build_heatmap(
            _revenue_series(),
            sector_of={},
            slots={"total_revenue": 1},
            metric="not_a_metric",
            sector_filter=None,
            client_filter=None,
            requested_scenario=None,
        )


def test_build_heatmap_missing_slot_raises_422():
    with pytest.raises(UnprocessableEntityError):
        ca.build_heatmap(
            _revenue_series(),
            sector_of={},
            slots={},  # leverage needs revenue/cogs/debts, none linked
            metric="leverage",
            sector_filter=None,
            client_filter=None,
            requested_scenario=None,
        )


def test_build_heatmap_unknown_scenario_raises():
    with pytest.raises(BadRequestError):
        ca.build_heatmap(
            _revenue_series(),
            sector_of={},
            slots={"total_revenue": 1},
            metric="revenue_growth",
            sector_filter=None,
            client_filter=None,
            requested_scenario="Nonexistent",
        )


def test_build_forecast_levels_and_delta():
    series = {
        "sector": {
            "Tech": {
                "total_assets": {
                    ca.SERIES_HISTORY: {2020: 100.0},
                    "Baseline": {2021: 110.0},
                }
            }
        }
    }
    payload = ca.build_forecast(
        series,
        slots={"total_assets": object()},
        sector="Tech",
        client_id=None,
        requested_keys=None,
        indexed=False,
    )
    assert payload["sector"] == "Tech"
    m = payload["metrics"][0]
    assert m["key"] == "total_assets"
    assert m["base_year"] == 2020
    assert m["value"] == 110.0
    assert m["delta_pct"] == 10.0  # (110-100)/100*100


def test_build_forecast_unknown_scope_raises_not_found():
    with pytest.raises(NotFoundError):
        ca.build_forecast(
            _revenue_series(),
            slots={"total_revenue": object()},
            sector="Nope",
            client_id=None,
            requested_keys=None,
            indexed=False,
        )
