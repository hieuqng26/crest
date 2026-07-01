"""
Tests for the revised demo data pipeline.

Validates:
  - demo_macro_forecast.csv has only MEV columns (no financial/sector columns)
  - demo_financial_portfolio.csv has the correct schema and base_year=2026
  - Portfolio merge logic (credit + financial) produces a complete dataset
  - Segment-based forecast fallback lookup works correctly

Run from services/server/:
    pytest tests/test_demo_data_pipeline.py -v

No Flask app context, DB, or Celery required.
"""

import os

import pandas as pd
import pytest

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "project", "data", "test_data")

MACRO_FORECAST_CSV = os.path.join(_DATA_DIR, "demo_macro_forecast.csv")
FINANCIAL_PORTFOLIO_CSV = os.path.join(_DATA_DIR, "demo_financial_portfolio.csv")
CREDIT_PORTFOLIO_CSV = os.path.join(_DATA_DIR, "demo_credit_portfolio.csv")

_MACRO_EXPECTED_COLS = {
    "date",
    "scenario",
    "client_id",
    "inflation_rate",
    "notional_gdp",
    "unemployment_rate",
    "coal_price",
    "oil_price",
}
_MACRO_REMOVED_COLS = {
    "sector",
    "subsector",
    "base_year",
    "total_assets",
    "total_longterm_debts",
    "total_shortterm_debts",
    "country",
}
_FIN_EXPECTED_COLS = {
    "date",
    "scenario",
    "client_id",
    "country",
    "sector",
    "subsector",
    "base_year",
    "total_assets",
    "total_longterm_debts",
    "total_shortterm_debts",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def macro_df():
    assert os.path.exists(MACRO_FORECAST_CSV), f"Missing: {MACRO_FORECAST_CSV}"
    return pd.read_csv(MACRO_FORECAST_CSV)


@pytest.fixture(scope="module")
def fin_df():
    assert os.path.exists(FINANCIAL_PORTFOLIO_CSV), f"Missing: {FINANCIAL_PORTFOLIO_CSV}"
    return pd.read_csv(FINANCIAL_PORTFOLIO_CSV)


@pytest.fixture(scope="module")
def credit_df():
    assert os.path.exists(CREDIT_PORTFOLIO_CSV), f"Missing: {CREDIT_PORTFOLIO_CSV}"
    return pd.read_csv(CREDIT_PORTFOLIO_CSV)


# ---------------------------------------------------------------------------
# TestDemoCSVSchemas
# ---------------------------------------------------------------------------


class TestDemoCSVSchemas:
    def test_macro_forecast_exact_columns(self, macro_df):
        assert set(macro_df.columns) == _MACRO_EXPECTED_COLS

    def test_macro_forecast_removed_columns_absent(self, macro_df):
        present_removed = _MACRO_REMOVED_COLS & set(macro_df.columns)
        assert not present_removed, f"Columns that should have been removed: {present_removed}"

    def test_macro_forecast_no_nulls_in_mev(self, macro_df):
        mev_cols = [
            "inflation_rate",
            "notional_gdp",
            "unemployment_rate",
            "coal_price",
            "oil_price",
        ]
        for col in mev_cols:
            null_count = macro_df[col].isnull().sum()
            assert null_count == 0, f"Column '{col}' has {null_count} nulls"

    def test_financial_portfolio_exact_columns(self, fin_df):
        assert set(fin_df.columns) == _FIN_EXPECTED_COLS

    def test_financial_portfolio_base_year_all_2026(self, fin_df):
        assert (fin_df["base_year"] == 2026).all(), "Not all base_year values are 2026"

    def test_financial_portfolio_has_all_credit_clients(self, fin_df, credit_df):
        fin_clients = set(fin_df["client_id"].unique())
        credit_clients = set(credit_df["client_id"].unique())
        missing = credit_clients - fin_clients
        assert not missing, f"Clients in credit portfolio not in financial portfolio: {missing}"

    def test_financial_portfolio_client_ids_match_macro_forecast(self, fin_df, macro_df):
        fin_clients = set(fin_df["client_id"].unique())
        macro_clients = set(macro_df["client_id"].unique())
        missing = macro_clients - fin_clients
        assert not missing, f"Clients in macro forecast not in financial portfolio: {missing}"


# ---------------------------------------------------------------------------
# TestForecastDataIntegrity
# ---------------------------------------------------------------------------


class TestForecastDataIntegrity:
    def test_mev_columns_are_numeric(self, macro_df):
        non_id_cols = [
            c for c in macro_df.columns if c not in ("date", "scenario", "client_id")
        ]
        for col in non_id_cols:
            assert pd.api.types.is_numeric_dtype(macro_df[col]), (
                f"Column '{col}' is not numeric: dtype={macro_df[col].dtype}"
            )

    def test_scenarios_present(self, macro_df):
        expected = {"Baseline", "Adverse", "Severely Adverse"}
        actual = set(macro_df["scenario"].unique())
        assert actual & expected, (
            f"No expected scenario found. Got: {actual}. Expected one of: {expected}"
        )

    def test_date_parseable(self, macro_df):
        parsed = pd.to_datetime(macro_df["date"], errors="coerce")
        null_count = parsed.isnull().sum()
        assert null_count == 0, f"{null_count} dates could not be parsed"

    def test_financial_portfolio_numeric_financial_cols(self, fin_df):
        for col in ("total_assets", "total_longterm_debts", "total_shortterm_debts", "base_year"):
            assert pd.api.types.is_numeric_dtype(fin_df[col]), (
                f"Column '{col}' is not numeric"
            )


# ---------------------------------------------------------------------------
# TestPortfolioMerge
# ---------------------------------------------------------------------------


class TestPortfolioMerge:
    def _merge(self, credit_df, fin_df):
        """Replicate the merge logic from run_credit_analysis.

        Only adds columns from fin_df that are not already present in credit_df
        to avoid duplicate-column suffixes (_x / _y).
        """
        fin_meta = (
            fin_df[["client_id", "country", "sector", "subsector"]]
            .drop_duplicates(subset=["client_id"])
        )
        new_cols = ["client_id"] + [
            c for c in fin_meta.columns if c != "client_id" and c not in credit_df.columns
        ]
        return credit_df.merge(fin_meta[new_cols], on="client_id", how="left")

    def test_merge_contains_required_kmv_columns(self, credit_df, fin_df):
        merged = self._merge(credit_df, fin_df)
        # credit_df already has sector and country; fin_df adds subsector
        required = {"client_id", "market_cap", "vol_equity", "risk_free_rate", "rating",
                    "subsector"}
        # sector and country come from credit_df
        required |= {"sector", "country"} & set(credit_df.columns)
        missing = required - set(merged.columns)
        assert not missing, f"Merged portfolio missing columns: {missing}"

    def test_merge_no_missing_clients(self, credit_df, fin_df):
        merged = self._merge(credit_df, fin_df)
        assert len(merged) == len(credit_df), (
            f"Row count changed after merge: {len(merged)} vs {len(credit_df)}"
        )

    def test_merge_subsector_present_and_non_null(self, credit_df, fin_df):
        merged = self._merge(credit_df, fin_df)
        assert "subsector" in merged.columns, "subsector column missing after merge"
        null_subsectors = merged["subsector"].isnull().sum()
        assert null_subsectors == 0, (
            f"{null_subsectors} clients have null subsector after merge — client_ids may not align"
        )

    def test_segment_lookup_fallback(self, fin_df):
        """
        When a client is missing from forecast_by_var but another client in the same
        (sector, subsector, country) segment has forecast data, the fallback lookup should
        return that representative client's data.
        """
        # Build fin_df_indexed from the real financial portfolio
        fin_meta = fin_df[["client_id", "country", "sector", "subsector"]].drop_duplicates(
            subset=["client_id"]
        )
        fin_df_indexed = fin_meta.set_index("client_id").to_dict("index")

        # Take the first two clients that share the same segment
        first_client = fin_meta.iloc[0]
        target_cid = first_client["client_id"]
        target_seg = (
            str(first_client["sector"]),
            str(first_client["subsector"]),
            str(first_client["country"]),
        )

        # Find another client in the same segment to act as the representative
        same_seg = fin_meta[
            (fin_meta["sector"] == first_client["sector"])
            & (fin_meta["subsector"] == first_client["subsector"])
            & (fin_meta["country"] == first_client["country"])
            & (fin_meta["client_id"] != target_cid)
        ]
        if same_seg.empty:
            pytest.skip("No two clients share the same (sector, subsector, country) segment")

        rep_cid = same_seg.iloc[0]["client_id"]

        # Synthetic forecast: only rep_cid has data, target_cid is absent
        dummy_forecast = {
            "Baseline": {2027: 1000.0, 2028: 1050.0},
        }
        forecast_by_var = {
            "total_assets": {rep_cid: dummy_forecast},
            "short_term_debts": {rep_cid: dummy_forecast},
            "long_term_debts": {rep_cid: dummy_forecast},
        }

        # Build _segment_to_cid exactly as the task does
        _segment_to_cid: dict[tuple, str] = {}
        for _cid, _meta in fin_df_indexed.items():
            _seg = (
                str(_meta.get("sector", "")),
                str(_meta.get("subsector", "")),
                str(_meta.get("country", "")),
            )
            if _seg not in _segment_to_cid and any(
                _cid in forecast_by_var[k] for k in forecast_by_var
            ):
                _segment_to_cid[_seg] = _cid

        # Simulate looking up target_cid (absent) → fallback via segment
        ta_by_scen = forecast_by_var["total_assets"].get(target_cid, {})
        assert not ta_by_scen, "target_cid should not be in forecast_by_var directly"

        rep = _segment_to_cid.get(target_seg)
        assert rep is not None, f"No segment representative found for {target_seg}"
        assert rep == rep_cid

        ta_fallback = forecast_by_var["total_assets"].get(rep, {})
        assert "Baseline" in ta_fallback
        assert ta_fallback["Baseline"][2027] == pytest.approx(1000.0)
