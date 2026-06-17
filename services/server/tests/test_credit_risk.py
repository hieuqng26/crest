"""
End-to-end tests for the KMV + ECL pipeline.

Run from services/server/:
    pytest tests/test_credit_risk.py -v

No Flask app context or database required — the core functions are pure
pandas/numpy/scipy.
"""

import importlib.util
import sys
import os

import numpy as np
import pandas as pd
import pytest


def _import_module(name: str, rel_path: str):
    """Import a module by file path, bypassing project/__init__.py (which pulls Flask)."""
    abs_path = os.path.join(os.path.dirname(__file__), "..", rel_path)
    spec = importlib.util.spec_from_file_location(name, abs_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Stub project.logger before importing modules that reference it
import logging
import types

_logger_stub = types.ModuleType("project.logger")
_logger_stub.get_logger = logging.getLogger
sys.modules.setdefault("project", types.ModuleType("project"))
sys.modules["project.logger"] = _logger_stub

_ecl_mod    = _import_module("ecl",         "project/core/credit_risk/ecl.py")
_kmv_mod    = _import_module("kmv",         "project/core/credit_risk/kmv.py")
_mock_mod   = _import_module("mock_credit", "project/core/credit_risk/mock_credit.py")

compute_ecl    = _ecl_mod.compute_ecl
run_kmv        = _kmv_mod.run_kmv
mock_credit_data  = _mock_mod.mock_credit_data
mock_kmv_forecast = _mock_mod.mock_kmv_forecast

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Matches the ratings used in demo_credit_portfolio.csv / mock_credit_data
_RATINGS = [
    "Aaa1", "Aaa2", "Aaa3",
    "Aa1",  "Aa2",  "Aa3",
    "A1",   "A2",   "A3",
    "Baa1", "Baa2", "Baa3",
    "Ba1",  "Ba2",
    "B1",   "B2",
    "Caa1", "Caa2", "Caa3",
]
_PD_VALUES = [
    0.0001, 0.0002, 0.0003,
    0.0005, 0.0007, 0.0010,
    0.0015, 0.0020, 0.0030,
    0.0050, 0.0070, 0.0100,
    0.0200, 0.0300,
    0.0500, 0.0800,
    0.1500, 0.2500, 0.4000,
]


@pytest.fixture(scope="module")
def pd_rating_df():
    return pd.DataFrame(
        [{"Category": i + 1, "Rating": r, "PD": p}
         for i, (r, p) in enumerate(zip(_RATINGS, _PD_VALUES))]
    )


@pytest.fixture(scope="module")
def credit_df():
    """20-client demo portfolio (same file the frontend uploads)."""
    csv_path = os.path.join(
        os.path.dirname(__file__),
        "..", "project", "data", "test_data", "demo_credit_portfolio.csv",
    )
    if os.path.exists(csv_path):
        return pd.read_csv(csv_path)
    return mock_credit_data(n_clients=20)


def _contiguous_forecast(client_id: str, base_year: int = 2020, n_years: int = 10):
    """Standard mock forecast — contiguous years."""
    return mock_kmv_forecast(client_id, base_year=base_year, n_years=n_years)


def _sparse_forecast(client_id: str, base_year: int = 2020, n_years: int = 15, step: int = 2):
    """Forecast with non-contiguous calendar years (every `step` years).
    This replicates real calibration data where different clients appear at
    different time steps, exposing the len(AT) vs max_year-base_year mismatch."""
    full = mock_kmv_forecast(client_id, base_year=base_year, n_years=n_years)
    keep = [base_year + i * step for i in range(n_years // step)]
    return full[full["YEAR"].isin(keep)].copy().reset_index(drop=True)


def _run_pipeline(com_info, forecast, pd_rating_df, exposure=1_000_000,
                  discount_rate=0.05, lifetime_horizon=5):
    kmv_df = run_kmv(com_info, forecast, pd_rating_df)
    ecl_df = compute_ecl(kmv_df, exposure, discount_rate, lifetime_horizon)
    return kmv_df, ecl_df


# ---------------------------------------------------------------------------
# KMV tests
# ---------------------------------------------------------------------------

class TestRunKMV:

    def test_contiguous_years_shape(self, pd_rating_df):
        forecast = _contiguous_forecast("C0001", n_years=10)
        com_info = {"E0": 5e9, "volE": 0.25, "r": 0.03, "rating": "A1"}
        kmv = run_kmv(com_info, forecast, pd_rating_df)

        scenarios = forecast["SCENARIO"].unique()
        n_years = len(forecast[forecast["SCENARIO"] == scenarios[0]])
        assert len(kmv) == len(scenarios) * n_years
        assert set(kmv.columns) >= {"YEAR", "SCENARIO", "PD", "LGD", "DTD", "Rating"}

    def test_sparse_years_shape(self, pd_rating_df):
        """Non-contiguous years must not cause array length mismatch."""
        forecast = _sparse_forecast("C0001", n_years=15, step=2)  # 7 or 8 years
        com_info = {"E0": 5e9, "volE": 0.25, "r": 0.03, "rating": "A1"}
        kmv = run_kmv(com_info, forecast, pd_rating_df)

        scenarios = forecast["SCENARIO"].unique()
        n_rows = len(forecast[forecast["SCENARIO"] == scenarios[0]])
        assert len(kmv) == len(scenarios) * n_rows

    def test_output_years_match_input(self, pd_rating_df):
        """YEAR column in output must equal YEAR column from input forecast."""
        forecast = _sparse_forecast("C0002", step=3)
        com_info = {"E0": 2e9, "volE": 0.30, "r": 0.02, "rating": "Baa1"}
        kmv = run_kmv(com_info, forecast, pd_rating_df)

        for scen in forecast["SCENARIO"].unique():
            expected = sorted(forecast[forecast["SCENARIO"] == scen]["YEAR"].tolist())
            actual = sorted(kmv[kmv["SCENARIO"] == scen]["YEAR"].tolist())
            assert actual == expected, f"YEAR mismatch for scenario {scen}"

    def test_pd_in_0_1_range(self, pd_rating_df):
        forecast = _contiguous_forecast("C0003", n_years=8)
        com_info = {"E0": 1e10, "volE": 0.20, "r": 0.04, "rating": "Aa2"}
        kmv = run_kmv(com_info, forecast, pd_rating_df)

        assert (kmv["PD"] >= 0).all() and (kmv["PD"] <= 1).all()
        assert (kmv["LGD"] >= 0).all() and (kmv["LGD"] <= 1).all()

    def test_all_scenarios_present(self, pd_rating_df):
        forecast = _contiguous_forecast("C0004", n_years=10)
        com_info = {"E0": 8e9, "volE": 0.35, "r": 0.025, "rating": "B1"}
        kmv = run_kmv(com_info, forecast, pd_rating_df)

        assert set(kmv["SCENARIO"].unique()) == {"Baseline", "Upside", "Downside"}

    def test_unknown_rating_raises(self, pd_rating_df):
        forecast = _contiguous_forecast("C0005")
        com_info = {"E0": 5e9, "volE": 0.25, "r": 0.03, "rating": "UNKNOWN"}
        with pytest.raises(ValueError, match="Rating 'UNKNOWN' not found"):
            run_kmv(com_info, forecast, pd_rating_df)

    def test_invalid_e0_raises(self, pd_rating_df):
        forecast = _contiguous_forecast("C0006")
        com_info = {"E0": 0, "volE": 0.25, "r": 0.03, "rating": "A1"}
        with pytest.raises(ValueError, match="Invalid market capitalisation"):
            run_kmv(com_info, forecast, pd_rating_df)

    def test_too_few_years_raises(self, pd_rating_df):
        """Forecast with only 1 distinct year must raise."""
        forecast = _contiguous_forecast("C0007", n_years=10)
        forecast = forecast[forecast["YEAR"] == forecast["YEAR"].min()].copy()
        com_info = {"E0": 5e9, "volE": 0.25, "r": 0.03, "rating": "A1"}
        with pytest.raises(ValueError, match="at least 2 distinct years"):
            run_kmv(com_info, forecast, pd_rating_df)

    def test_minimum_two_years(self, pd_rating_df):
        """Exactly 2 years per scenario should succeed."""
        full = _contiguous_forecast("C0008", n_years=10)
        base_year = full["YEAR"].min()
        forecast = full[full["YEAR"].isin([base_year, base_year + 1])].copy()
        com_info = {"E0": 5e9, "volE": 0.25, "r": 0.03, "rating": "A1"}
        kmv = run_kmv(com_info, forecast, pd_rating_df)
        assert len(kmv) == 3 * 2  # 3 scenarios × 2 years


# ---------------------------------------------------------------------------
# ECL tests
# ---------------------------------------------------------------------------

class TestComputeECL:

    def _kmv(self, client_id, forecast, pd_rating_df, rating="A1"):
        com_info = {"E0": 5e9, "volE": 0.25, "r": 0.03, "rating": rating}
        return run_kmv(com_info, forecast, pd_rating_df)

    def test_contiguous_output_shape(self, pd_rating_df):
        forecast = _contiguous_forecast("C0001", n_years=10)
        kmv = self._kmv("C0001", forecast, pd_rating_df)
        ecl = compute_ecl(kmv, exposure=1_000_000, r=0.05, lifetime_horizon=5)

        assert set(ecl.columns) >= {"YEAR", "SCENARIO", "ECL_12M", "ECL_Lifetime"}
        # one row per (scenario, year+1) — the +1 is the prepended base_year-1 anchor row
        n_years = len(forecast[forecast["SCENARIO"] == "Baseline"])
        assert len(ecl[ecl["SCENARIO"] == "Baseline"]) == n_years + 1

    def test_sparse_output_shape(self, pd_rating_df):
        """Non-contiguous years must not cause length mismatch in ECL."""
        forecast = _sparse_forecast("C0001", step=2)
        kmv = self._kmv("C0001", forecast, pd_rating_df)
        ecl = compute_ecl(kmv, exposure=1_000_000, r=0.05, lifetime_horizon=5)

        n_years = len(forecast[forecast["SCENARIO"] == "Baseline"])
        assert len(ecl[ecl["SCENARIO"] == "Baseline"]) == n_years + 1

    def test_ecl_non_negative(self, pd_rating_df):
        forecast = _contiguous_forecast("C0002", n_years=8)
        kmv = self._kmv("C0002", forecast, pd_rating_df)
        ecl = compute_ecl(kmv, exposure=500_000, r=0.04, lifetime_horizon=3)

        assert (ecl["ECL_12M"].fillna(0) >= 0).all()
        assert (ecl["ECL_Lifetime"].fillna(0) >= 0).all()

    def test_ecl_bounded_by_exposure(self, pd_rating_df):
        exposure = 2_000_000
        forecast = _contiguous_forecast("C0003", n_years=10)
        kmv = self._kmv("C0003", forecast, pd_rating_df, rating="Caa1")
        ecl = compute_ecl(kmv, exposure=exposure, r=0.05, lifetime_horizon=5)

        assert (ecl["ECL_12M"].fillna(0) <= exposure * 1.01).all()
        assert (ecl["ECL_Lifetime"].fillna(0) <= exposure * 1.01).all()

    def test_scenarios_preserved(self, pd_rating_df):
        forecast = _contiguous_forecast("C0004", n_years=8)
        kmv = self._kmv("C0004", forecast, pd_rating_df)
        ecl = compute_ecl(kmv, exposure=1_000_000, r=0.05, lifetime_horizon=5)

        assert set(ecl["SCENARIO"].unique()) == {"Baseline", "Upside", "Downside"}

    def test_drop_tail(self, pd_rating_df):
        n_years, horizon = 10, 5
        forecast = _contiguous_forecast("C0005", n_years=n_years)
        kmv = self._kmv("C0005", forecast, pd_rating_df)
        ecl_full = compute_ecl(kmv, 1_000_000, 0.05, lifetime_horizon=horizon, drop_tail=False)
        ecl_trim = compute_ecl(kmv, 1_000_000, 0.05, lifetime_horizon=horizon, drop_tail=True)

        assert len(ecl_trim) < len(ecl_full)


# ---------------------------------------------------------------------------
# Full pipeline — all clients from demo_credit_portfolio
# ---------------------------------------------------------------------------

class TestFullPipeline:

    def _run_all(self, credit_df, pd_rating_df, forecast_fn, label):
        errors = []
        results = {}
        for _, row in credit_df.iterrows():
            cid = str(row["client_id"])
            com_info = {
                "E0": float(row["market_cap"]),
                "volE": float(row["vol_equity"]),
                "r": float(row["risk_free_rate"]),
                "rating": str(row["rating"]),
            }
            # Skip clients whose rating isn't in the table
            if com_info["rating"] not in _RATINGS:
                continue
            try:
                forecast = forecast_fn(cid)
                kmv, ecl = _run_pipeline(com_info, forecast, pd_rating_df)
                results[cid] = {"kmv_rows": len(kmv), "ecl_rows": len(ecl)}
            except Exception as exc:
                errors.append(f"{cid}: {exc}")

        if errors:
            pytest.fail(
                f"{label} — {len(errors)}/{len(credit_df)} clients failed:\n"
                + "\n".join(errors[:10])
            )
        return results

    def test_contiguous_all_clients(self, credit_df, pd_rating_df):
        self._run_all(
            credit_df, pd_rating_df,
            lambda cid: _contiguous_forecast(cid, n_years=10),
            "contiguous",
        )

    def test_sparse_all_clients(self, credit_df, pd_rating_df):
        """Simulate non-contiguous calibration coverage — the scenario that was
        causing operands broadcast / length mismatch errors in production."""
        self._run_all(
            credit_df, pd_rating_df,
            lambda cid: _sparse_forecast(cid, n_years=20, step=2),
            "sparse (every-other-year)",
        )

    def test_very_sparse_all_clients(self, credit_df, pd_rating_df):
        """Even sparser — 3-year gaps, only 4 time points."""
        self._run_all(
            credit_df, pd_rating_df,
            lambda cid: _sparse_forecast(cid, n_years=12, step=3),
            "very sparse (every-3rd-year)",
        )

    def test_output_columns_complete(self, credit_df, pd_rating_df):
        row = credit_df.iloc[0]
        cid = str(row["client_id"])
        if str(row["rating"]) not in _RATINGS:
            pytest.skip("rating not in test table")
        com_info = {
            "E0": float(row["market_cap"]),
            "volE": float(row["vol_equity"]),
            "r": float(row["risk_free_rate"]),
            "rating": str(row["rating"]),
        }
        kmv, ecl = _run_pipeline(com_info, _contiguous_forecast(cid), pd_rating_df)

        assert {"YEAR", "SCENARIO", "PD", "LGD", "DTD", "Rating", "Marginal PD",
                "TOTAL_ASSET_T", "Tenor"}.issubset(set(kmv.columns))
        assert {"YEAR", "SCENARIO", "ECL_12M", "ECL_Lifetime"}.issubset(set(ecl.columns))

    def test_no_nulls_in_key_columns(self, credit_df, pd_rating_df):
        row = credit_df.iloc[1]
        cid = str(row["client_id"])
        if str(row["rating"]) not in _RATINGS:
            pytest.skip("rating not in test table")
        com_info = {
            "E0": float(row["market_cap"]),
            "volE": float(row["vol_equity"]),
            "r": float(row["risk_free_rate"]),
            "rating": str(row["rating"]),
        }
        kmv, ecl = _run_pipeline(com_info, _contiguous_forecast(cid), pd_rating_df)

        for col in ("PD", "LGD", "DTD"):
            assert not kmv[col].isnull().any(), f"NaN in kmv[{col!r}]"
        for col in ("ECL_12M", "ECL_Lifetime"):
            assert not ecl[col].isnull().any(), f"NaN in ecl[{col!r}]"
