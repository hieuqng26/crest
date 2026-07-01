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

_DATA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "project", "data", "test_data"
)

MACRO_FORECAST_CSV = os.path.join(_DATA_DIR, "demo_macro_forecast.csv")
FINANCIAL_PORTFOLIO_CSV = os.path.join(_DATA_DIR, "demo_financial_portfolio.csv")
CREDIT_PORTFOLIO_CSV = os.path.join(_DATA_DIR, "demo_credit_portfolio.csv")

_MACRO_EXPECTED_COLS = {
    "date",
    "scenario",
    "inflation_rate",
    "notional_gdp",
    "unemployment_rate",
    "coal_price",
    "oil_price",
}
_MACRO_REMOVED_COLS = {
    "client_id",
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
    assert os.path.exists(FINANCIAL_PORTFOLIO_CSV), (
        f"Missing: {FINANCIAL_PORTFOLIO_CSV}"
    )
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
        assert not present_removed, (
            f"Columns that should have been removed: {present_removed}"
        )

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
        assert not missing, (
            f"Clients in credit portfolio not in financial portfolio: {missing}"
        )

    def test_macro_forecast_is_portfolio_wide(self, macro_df):
        """
        demo_macro_forecast.csv carries no client_id/sector — it's a single scenario
        table (one row per date x scenario) applied uniformly to every client in the
        credit risk run, not a per-client dataset.
        """
        assert not macro_df.duplicated(subset=["date", "scenario"]).any(), (
            "Expected exactly one row per (date, scenario) pair"
        )


# ---------------------------------------------------------------------------
# TestForecastDataIntegrity
# ---------------------------------------------------------------------------


class TestForecastDataIntegrity:
    def test_mev_columns_are_numeric(self, macro_df):
        non_id_cols = [c for c in macro_df.columns if c not in ("date", "scenario")]
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
        for col in (
            "total_assets",
            "total_longterm_debts",
            "total_shortterm_debts",
            "base_year",
        ):
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
        fin_meta = fin_df[
            ["client_id", "country", "sector", "subsector"]
        ].drop_duplicates(subset=["client_id"])
        new_cols = ["client_id"] + [
            c
            for c in fin_meta.columns
            if c != "client_id" and c not in credit_df.columns
        ]
        return credit_df.merge(fin_meta[new_cols], on="client_id", how="left")

    def test_merge_contains_required_kmv_columns(self, credit_df, fin_df):
        merged = self._merge(credit_df, fin_df)
        # credit_df already has sector and country; fin_df adds subsector
        required = {
            "client_id",
            "market_cap",
            "vol_equity",
            "risk_free_rate",
            "rating",
            "subsector",
        }
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
        fin_meta = fin_df[
            ["client_id", "country", "sector", "subsector"]
        ].drop_duplicates(subset=["client_id"])
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
            pytest.skip(
                "No two clients share the same (sector, subsector, country) segment"
            )

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

    def test_portfolio_wide_forecast_fallback(self, credit_df):
        """
        demo_macro_forecast.csv has no client_id, so ForecastRunResult rows come back
        with client_id=None. run_credit_analysis indexes those under the None key and
        applies that single trajectory to every client — replicate that lookup here.
        """
        dummy_forecast = {"Baseline": {2027: 1000.0, 2028: 1050.0}}
        forecast_by_var = {
            "total_assets": {None: dummy_forecast},
            "short_term_debts": {None: dummy_forecast},
            "long_term_debts": {None: dummy_forecast},
        }

        for client_id in credit_df["client_id"].tolist():
            ta_by_scen = forecast_by_var["total_assets"].get(client_id, {})
            assert not ta_by_scen, "No client should match directly by client_id"

            # Portfolio-wide fallback: same lookup run_credit_analysis performs
            if not ta_by_scen:
                ta_by_scen = forecast_by_var["total_assets"].get(None, {})
            assert ta_by_scen == dummy_forecast, (
                f"Client {client_id} did not receive the portfolio-wide forecast"
            )


# ---------------------------------------------------------------------------
# TestSegmentRouting
#
# When a calibration is segmented, run_forecast scores every trained segment
# against the (MEV-only, portfolio-wide) forecast dataset, tagging each output
# row with its segment_key. run_credit_analysis then routes each client to its
# own segment's trajectory via _resolve_segment_key (exact subsector/country
# match -> "Others" bucket -> any segment for that sector). This class
# replicates that resolution algorithm exactly and validates it against real
# demo data.
# ---------------------------------------------------------------------------


def _resolve_segment_key(seg_info: dict, sector: str, subsector: str, country: str):
    """Mirrors run_credit_analysis._resolve_segment_key in tasks.py."""
    split_by = seg_info["split_by"].get(sector)
    if not split_by:
        return None
    split_val = subsector if split_by == "subsector" else country
    top_vals = seg_info["top_values"].get(sector, set())
    if split_val in top_vals:
        return f"{sector}__{split_val}"
    if "Others" in top_vals:
        return f"{sector}__Others"
    return seg_info["fallback"].get(sector)


class TestSegmentRouting:
    def test_exact_subsector_match(self, fin_df):
        row = fin_df.iloc[0]
        sector, subsector, country = row["sector"], row["subsector"], row["country"]
        seg_info = {
            "split_by": {sector: "subsector"},
            "top_values": {sector: {subsector, "Others"}},
            "fallback": {sector: f"{sector}__Others"},
        }
        assert _resolve_segment_key(seg_info, sector, subsector, country) == (
            f"{sector}__{subsector}"
        )

    def test_falls_back_to_others_bucket(self, fin_df):
        row = fin_df.iloc[0]
        sector, subsector, country = row["sector"], row["subsector"], row["country"]
        seg_info = {
            "split_by": {sector: "subsector"},
            # exact subsector was not among the top-N trained segments
            "top_values": {sector: {"SomeOtherSubsector", "Others"}},
            "fallback": {sector: f"{sector}__SomeOtherSubsector"},
        }
        assert (
            _resolve_segment_key(seg_info, sector, subsector, country)
            == f"{sector}__Others"
        )

    def test_falls_back_to_sector_fallback_when_no_others_bucket(self, fin_df):
        row = fin_df.iloc[0]
        sector, subsector, country = row["sector"], row["subsector"], row["country"]
        seg_info = {
            "split_by": {sector: "subsector"},
            "top_values": {sector: {"SomeOtherSubsector"}},  # no "Others" bucket
            "fallback": {sector: f"{sector}__SomeOtherSubsector"},
        }
        assert (
            _resolve_segment_key(seg_info, sector, subsector, country)
            == f"{sector}__SomeOtherSubsector"
        )

    def test_sector_not_segmented_returns_none(self, fin_df):
        row = fin_df.iloc[0]
        sector, subsector, country = row["sector"], row["subsector"], row["country"]
        seg_info = {"split_by": {}, "top_values": {}, "fallback": {}}
        assert _resolve_segment_key(seg_info, sector, subsector, country) is None

    def test_country_split_by_routes_on_country(self, fin_df):
        row = fin_df.iloc[0]
        sector, country = row["sector"], row["country"]
        seg_info = {
            "split_by": {sector: "country"},
            "top_values": {sector: {country}},
            "fallback": {sector: f"{sector}__{country}"},
        }
        assert (
            _resolve_segment_key(seg_info, sector, "AnySubsector", country)
            == f"{sector}__{country}"
        )

    def test_all_clients_route_to_a_segment_for_their_own_sector(self, fin_df):
        """
        Realistic scenario: segment all 10 sectors by subsector (top-5 + Others).
        Every client should resolve to a segment_key trained for its own sector —
        never a different sector's segment, never None.
        """
        seg_info = {"split_by": {}, "top_values": {}, "fallback": {}}
        for sector, group in fin_df.groupby("sector"):
            top5 = group["subsector"].value_counts().head(5).index.tolist()
            seg_info["split_by"][sector] = "subsector"
            seg_info["top_values"][sector] = set(top5) | {"Others"}
            seg_info["fallback"][sector] = f"{sector}__{top5[0]}"

        for _, row in fin_df.drop_duplicates(subset=["client_id"]).iterrows():
            resolved = _resolve_segment_key(
                seg_info, row["sector"], row["subsector"], row["country"]
            )
            assert resolved is not None, f"No segment resolved for {row['client_id']}"
            assert resolved.startswith(f"{row['sector']}__"), (
                f"Client {row['client_id']} routed to wrong sector's segment: {resolved}"
            )

    def test_different_subsectors_route_to_different_segments(self, credit_df, fin_df):
        """
        Energy clients in different subsectors must resolve to different segment_keys
        — i.e. they get different forecast trajectories, not one uniform trajectory.
        Multiple clients share a subsector (and therefore a segment_key) by design —
        this asserts one segment per distinct subsector, not one segment per client.
        """
        energy_clients = credit_df[credit_df["sector"] == "Energy"][
            "client_id"
        ].tolist()
        fin_meta = fin_df[
            ["client_id", "sector", "subsector", "country"]
        ].drop_duplicates(subset=["client_id"])
        energy_subsectors = set(
            fin_meta[fin_meta["sector"] == "Energy"]["subsector"].unique()
        )
        seg_info = {
            "split_by": {"Energy": "subsector"},
            "top_values": {"Energy": energy_subsectors | {"Others"}},
            "fallback": {"Energy": "Energy__Oil & Gas"},
        }
        resolved_keys = set()
        clients_by_key: dict = {}
        for cid in energy_clients:
            row = fin_meta[fin_meta["client_id"] == cid].iloc[0]
            key = _resolve_segment_key(
                seg_info, row["sector"], row["subsector"], row["country"]
            )
            resolved_keys.add(key)
            clients_by_key.setdefault(key, set()).add(cid)

        assert len(resolved_keys) == len(energy_subsectors), (
            f"Expected {len(energy_subsectors)} distinct segments "
            f"(one per subsector), got {resolved_keys}"
        )
        for key, cids in clients_by_key.items():
            assert len(cids) > 1, (
                f"Expected multiple clients routed to {key}, got {cids}"
            )
