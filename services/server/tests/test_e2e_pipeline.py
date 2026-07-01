"""
End-to-end pipeline tests: calibration → forecast → credit risk.

Exercises ElasticNet calibration (R² validation), segmentation logic,
forecast application, KMV, and ECL — all without Flask, DB, Celery, or MinIO.

Run from services/server/:
    pytest tests/test_e2e_pipeline.py -v -s
"""

import importlib.util
import logging
import os
import sys
import types
import warnings

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Lightweight module loader (avoids pulling in Flask via project/__init__.py)
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(__file__)
_SERVER_ROOT = os.path.join(_HERE, "..")
_DATA_DIR = os.path.join(_SERVER_ROOT, "project", "data", "test_data")


def _import_module(name: str, rel_path: str):
    abs_path = os.path.join(_SERVER_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, abs_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Stub project.logger so core modules don't pull Flask
_logger_stub = types.ModuleType("project.logger")
_logger_stub.get_logger = logging.getLogger
sys.modules.setdefault("project", types.ModuleType("project"))
sys.modules["project.logger"] = _logger_stub

# Import core ML modules directly
_base_mod = _import_module(
    "project.core.model_registry.base", "project/core/model_registry/base.py"
)
_diag_mod = _import_module(
    "project.core.model_registry.diagnostics",
    "project/core/model_registry/diagnostics.py",
)
_en_mod = _import_module(
    "project.core.model_registry.plugins.elastic_net",
    "project/core/model_registry/plugins/elastic_net.py",
)
_kmv_mod = _import_module("kmv_e2e", "project/core/credit_risk/kmv.py")
_ecl_mod = _import_module("ecl_e2e", "project/core/credit_risk/ecl.py")

ElasticNetPlugin = _en_mod.ElasticNetPlugin
ElasticNetParams = _en_mod.ElasticNetParams
run_kmv = _kmv_mod.run_kmv
compute_ecl = _ecl_mod.compute_ecl

# ---------------------------------------------------------------------------
# Constants / shared fixtures
# ---------------------------------------------------------------------------

FEATURES = [
    "inflation_rate",
    "notional_gdp",
    "unemployment_rate",
    "coal_price",
    "oil_price",
]
TARGETS = ["total_assets", "total_longterm_debts", "total_shortterm_debts"]

_RATINGS = [
    "Aaa1",
    "Aaa2",
    "Aaa3",
    "Aa1",
    "Aa2",
    "Aa3",
    "A1",
    "A2",
    "A3",
    "Baa1",
    "Baa2",
    "Baa3",
    "Ba1",
    "Ba2",
    "B1",
    "B2",
    "Caa1",
    "Caa2",
    "Caa3",
]
_PD_VALUES = [
    0.0001,
    0.0002,
    0.0003,
    0.0005,
    0.0007,
    0.0010,
    0.0015,
    0.0020,
    0.0030,
    0.0050,
    0.0070,
    0.0100,
    0.0200,
    0.0300,
    0.0500,
    0.0800,
    0.1500,
    0.2500,
    0.4000,
]

MIN_R2 = 0.20
MEDIAN_R2 = 0.50


@pytest.fixture(scope="module")
def merged_df():
    path = os.path.join(_DATA_DIR, "financials_macro_merged.csv")
    assert os.path.exists(path), f"Missing: {path}"
    return pd.read_csv(path)


@pytest.fixture(scope="module")
def credit_df():
    path = os.path.join(_DATA_DIR, "demo_credit_portfolio.csv")
    assert os.path.exists(path), f"Missing: {path}"
    return pd.read_csv(path)


@pytest.fixture(scope="module")
def macro_forecast_df():
    path = os.path.join(_DATA_DIR, "demo_macro_forecast.csv")
    assert os.path.exists(path), f"Missing: {path}"
    return pd.read_csv(path)


@pytest.fixture(scope="module")
def fin_df():
    path = os.path.join(_DATA_DIR, "demo_financial_portfolio.csv")
    assert os.path.exists(path), f"Missing: {path}"
    return pd.read_csv(path)


@pytest.fixture(scope="module")
def pd_rating_df():
    return pd.DataFrame(
        [
            {"Category": i + 1, "Rating": r, "PD": p}
            for i, (r, p) in enumerate(zip(_RATINGS, _PD_VALUES))
        ]
    )


def _fit_elasticnet(X_train, y_train, X_val, y_val, alpha: float = 0.01) -> tuple:
    """Fit ElasticNet on scaled features; return (plugin, scaler, val_r2).

    alpha=0.01 rather than the default 1.0 — ElasticNet's default regularisation is
    calibrated for unit-variance responses. Targets like total_shortterm_debts have
    mean ~0.5 in these units, so alpha=1.0 pushes nearly all coefficients to zero.
    In the production workflow users would tune alpha (or run a grid/random search);
    0.01 gives a fair representation of the achievable R² for data-quality validation.
    """
    scaler = StandardScaler()
    Xt = scaler.fit_transform(X_train)
    Xv = scaler.transform(X_val)

    plugin = ElasticNetPlugin()
    params = ElasticNetParams(alpha=alpha)
    plugin.fit(Xt, y_train, params)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        y_pred = plugin.predict(Xv)

    valid = np.isfinite(y_pred)
    r2 = float(r2_score(y_val[valid], y_pred[valid])) if valid.any() else -999.0
    return plugin, scaler, r2


def _top_subsectors(df_sector: pd.DataFrame, n: int = 5) -> list[str]:
    """Return top-N subsectors by row count (deterministic, matches task logic)."""
    return df_sector["subsector"].value_counts().head(n).index.tolist()


# ---------------------------------------------------------------------------
# TestCalibrationR2
# ---------------------------------------------------------------------------


class TestCalibrationR2:
    """
    Validate that ElasticNet achieves R² ≥ 0.20 per segment and median ≥ 0.50
    across all (sector × subsector) segments for each of the 3 target variables.
    """

    def _r2_across_segments(self, merged_df: pd.DataFrame, target: str) -> list[float]:
        r2_list = []
        failures = []
        for sector in sorted(merged_df["sector"].unique()):
            df_s = merged_df[merged_df["sector"] == sector]
            for subsector in _top_subsectors(df_s):
                df_seg = df_s[df_s["subsector"] == subsector]
                if len(df_seg) < 20:
                    continue
                X = df_seg[FEATURES].values
                y = df_seg[target].values
                X_train, X_val, y_train, y_val = train_test_split(
                    X, y, test_size=0.2, random_state=42
                )
                _, _, r2 = _fit_elasticnet(X_train, y_train, X_val, y_val)
                r2_list.append(r2)
                if r2 < MIN_R2:
                    failures.append(f"{sector}/{subsector}: R²={r2:.3f}")

        assert not failures, (
            f"Segments below R²={MIN_R2} for target='{target}':\n" + "\n".join(failures)
        )
        return r2_list

    def test_elasticnet_r2_total_assets(self, merged_df):
        r2s = self._r2_across_segments(merged_df, "total_assets")
        median = float(np.median(r2s))
        print(
            f"\ntotal_assets  — n_segments={len(r2s)}, median R²={median:.3f}, min={min(r2s):.3f}"
        )
        assert median >= MEDIAN_R2, (
            f"Median R²={median:.3f} < {MEDIAN_R2} for total_assets"
        )

    def test_elasticnet_r2_total_longterm_debts(self, merged_df):
        r2s = self._r2_across_segments(merged_df, "total_longterm_debts")
        median = float(np.median(r2s))
        print(
            f"\ntotal_longterm_debts — n_segments={len(r2s)}, median R²={median:.3f}, min={min(r2s):.3f}"
        )
        assert median >= MEDIAN_R2, (
            f"Median R²={median:.3f} < {MEDIAN_R2} for total_longterm_debts"
        )

    def test_elasticnet_r2_total_shortterm_debts(self, merged_df):
        r2s = self._r2_across_segments(merged_df, "total_shortterm_debts")
        median = float(np.median(r2s))
        print(
            f"\ntotal_shortterm_debts — n_segments={len(r2s)}, median R²={median:.3f}, min={min(r2s):.3f}"
        )
        assert median >= MEDIAN_R2, (
            f"Median R²={median:.3f} < {MEDIAN_R2} for total_shortterm_debts"
        )


# ---------------------------------------------------------------------------
# TestSegmentationLogic
# ---------------------------------------------------------------------------


class TestSegmentationLogic:
    """Validate that the subsector segmentation logic produces well-formed segments."""

    def test_top5_subsectors_per_sector(self, merged_df):
        for sector in merged_df["sector"].unique():
            df_s = merged_df[merged_df["sector"] == sector]
            top = _top_subsectors(df_s, n=5)
            assert 1 <= len(top) <= 5, (
                f"Unexpected segment count for {sector}: {len(top)}"
            )
            # Every top subsector must actually exist in this sector
            for sub in top:
                assert sub in df_s["subsector"].values, f"{sub} not in {sector}"

    def test_all_sectors_have_enough_segments(self, merged_df):
        for sector in merged_df["sector"].unique():
            df_s = merged_df[merged_df["sector"] == sector]
            n_sub = df_s["subsector"].nunique()
            assert n_sub >= 2, (
                f"Sector {sector} has only {n_sub} subsector(s) — need ≥ 2 for split"
            )

    def test_others_bucket_covers_remaining(self, merged_df):
        """Top-5 + Others must cover all rows in the sector."""
        for sector in merged_df["sector"].unique():
            df_s = merged_df[merged_df["sector"] == sector]
            top = _top_subsectors(df_s, n=5)
            in_top = df_s[df_s["subsector"].isin(top)]
            others = df_s[~df_s["subsector"].isin(top)]
            assert len(in_top) + len(others) == len(df_s)

    def test_segment_rows_sufficient_for_training(self, merged_df):
        """Each top-5 segment must have ≥ 50 rows (enough for 80/20 split)."""
        for sector in merged_df["sector"].unique():
            df_s = merged_df[merged_df["sector"] == sector]
            for sub in _top_subsectors(df_s, n=5):
                n = len(df_s[df_s["subsector"] == sub])
                assert n >= 50, f"{sector}/{sub} has only {n} rows"


# ---------------------------------------------------------------------------
# TestForecastPipeline
# ---------------------------------------------------------------------------


class TestForecastPipeline:
    """
    Train on one segment and apply to the (portfolio-wide) forecast dataset.

    demo_macro_forecast.csv carries no client_id/sector — it's a single MEV scenario
    table (one row per date x scenario). A forecast run scores that table with one
    segment's model, producing one trajectory that is applied to every client in
    that segment during credit risk analysis (see TestKmvEclEndToEnd).
    """

    @pytest.fixture(scope="class")
    def energy_model(self, merged_df):
        """Train ElasticNet on Energy/Oil & Gas and return (plugin, scaler)."""
        df_s = merged_df[
            (merged_df["sector"] == "Energy") & (merged_df["subsector"] == "Oil & Gas")
        ]
        X = df_s[FEATURES].values
        y = df_s["total_assets"].values
        X_train, _, y_train, _ = train_test_split(X, y, test_size=0.2, random_state=42)
        scaler = StandardScaler()
        Xt = scaler.fit_transform(X_train)
        plugin = ElasticNetPlugin()
        plugin.fit(Xt, y_train, ElasticNetParams(alpha=0.01))
        return plugin, scaler

    def test_forecast_produces_predictions(self, energy_model, macro_forecast_df):
        plugin, scaler = energy_model
        assert not macro_forecast_df.empty, "Macro forecast dataset is empty"

        X_fc = macro_forecast_df[FEATURES].values
        X_fc_s = scaler.transform(X_fc)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            preds = plugin.predict(X_fc_s)

        assert len(preds) == len(macro_forecast_df), "Prediction count mismatch"
        assert np.isfinite(preds).all(), "Non-finite predictions"
        assert (preds > 0).all(), "Negative asset predictions"

    def test_forecast_scenario_spread(self, energy_model, macro_forecast_df):
        """Baseline predictions should differ from Adverse (macro differs per scenario)."""
        plugin, scaler = energy_model

        base = macro_forecast_df[macro_forecast_df["scenario"] == "Baseline"]
        adv = macro_forecast_df[macro_forecast_df["scenario"] == "Adverse"]
        if base.empty or adv.empty:
            pytest.skip("Missing scenarios in macro forecast")

        X_base = scaler.transform(base[FEATURES].values)
        X_adv = scaler.transform(adv[FEATURES].values)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            p_base = plugin.predict(X_base)
            p_adv = plugin.predict(X_adv)

        # Baseline GDP is higher than Adverse → assets should be higher on average
        assert p_base.mean() > p_adv.mean(), (
            f"Expected Baseline mean ({p_base.mean():.2f}) > Adverse mean ({p_adv.mean():.2f})"
        )

    def test_all_segments_produce_positive_forecasts(
        self, merged_df, macro_forecast_df
    ):
        """Spot-check 3 sectors: train per top subsector, predict on forecast, all positive."""
        for sector in ["Energy", "Technology", "Materials"]:
            df_s = merged_df[merged_df["sector"] == sector]
            top_sub = _top_subsectors(df_s, n=1)[0]
            df_seg = df_s[df_s["subsector"] == top_sub]

            X = df_seg[FEATURES].values
            y = df_seg["total_assets"].values
            X_train, _, y_train, _ = train_test_split(
                X, y, test_size=0.2, random_state=42
            )
            scaler = StandardScaler()
            Xt = scaler.fit_transform(X_train)
            plugin = ElasticNetPlugin()
            plugin.fit(Xt, y_train, ElasticNetParams(alpha=0.01))

            X_fc_s = scaler.transform(macro_forecast_df[FEATURES].values)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                preds = plugin.predict(X_fc_s)
            assert (preds > 0).all(), f"Negative predictions for {sector}/{top_sub}"


# ---------------------------------------------------------------------------
# TestKmvEclEndToEnd
# ---------------------------------------------------------------------------


class TestKmvEclEndToEnd:
    """
    Validate KMV + ECL output correctness using real demo data.

    demo_macro_forecast.csv is portfolio-wide (no client_id) — one segment's 3
    calibrated models (total_assets/short_term_debts/long_term_debts) produce a
    single trajectory per scenario/year, which is then applied uniformly to every
    client in that segment (differentiated only by each client's own market_cap /
    vol_equity / rating in the KMV com_info), mirroring run_credit_analysis.
    """

    @pytest.fixture(scope="class")
    def trained_models(self, merged_df):
        """Train 3 ElasticNet models (one per target) on the Energy sector."""
        models = {}
        df_s = merged_df[
            (merged_df["sector"] == "Energy") & (merged_df["subsector"] == "Oil & Gas")
        ]
        for target in TARGETS:
            X = df_s[FEATURES].values
            y = df_s[target].values
            X_train, _, y_train, _ = train_test_split(
                X, y, test_size=0.2, random_state=42
            )
            scaler = StandardScaler()
            Xt = scaler.fit_transform(X_train)
            plugin = ElasticNetPlugin()
            plugin.fit(Xt, y_train, ElasticNetParams(alpha=0.01))
            models[target] = (plugin, scaler)
        return models

    @pytest.fixture(scope="class")
    def segment_forecast(self, macro_forecast_df, trained_models) -> pd.DataFrame:
        """Apply the 3 segment models to the portfolio-wide MEV table → KMV-ready DataFrame."""
        df = macro_forecast_df.copy()
        df["YEAR"] = pd.to_datetime(df["date"], dayfirst=False).dt.year

        rows = []
        for scen in ["Baseline", "Adverse", "Severely Adverse"]:
            df_sc = df[df["scenario"] == scen].sort_values("YEAR")
            if df_sc.empty:
                continue
            X_fc = df_sc[FEATURES].values
            preds = {}
            for target, (plugin, scaler) in trained_models.items():
                X_s = scaler.transform(X_fc)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    preds[target] = plugin.predict(X_s)

            for i, (_, row) in enumerate(df_sc.iterrows()):
                rows.append(
                    {
                        "YEAR": int(row["YEAR"]),
                        "SCENARIO": scen,
                        "Total_Asset": float(max(1.0, preds["total_assets"][i])),
                        "CL": float(max(0.1, preds["total_shortterm_debts"][i])),
                        "NonCL": float(max(0.1, preds["total_longterm_debts"][i])),
                    }
                )
        return pd.DataFrame(rows)

    def test_kmv_output_structure(self, credit_df, segment_forecast, pd_rating_df):
        """KMV produces expected columns and valid PD values for 3 clients sharing the segment forecast."""
        assert segment_forecast["YEAR"].nunique() >= 2, "Need >=2 years for KMV"
        energy_clients = credit_df[credit_df["sector"] == "Energy"][
            "client_id"
        ].tolist()[:3]
        if not energy_clients:
            pytest.skip("No Energy clients in credit portfolio")

        for cid in energy_clients:
            row = credit_df[credit_df["client_id"] == cid].iloc[0]
            com_info = {
                "E0": float(row["market_cap"]) / 1e6,  # convert to millions
                "r": float(row["risk_free_rate"]),
                "volE": float(row["vol_equity"]),
                "rating": str(row["rating"]),
            }
            if com_info["rating"] not in pd_rating_df["Rating"].values:
                continue

            kmv_out = run_kmv(com_info, segment_forecast, pd_rating_df)

            assert "DTD" in kmv_out.columns
            assert "PD" in kmv_out.columns
            assert "LGD" in kmv_out.columns
            assert "SCENARIO" in kmv_out.columns
            assert "YEAR" in kmv_out.columns
            assert kmv_out["PD"].between(0, 1).all(), f"PD out of [0,1] for {cid}"
            assert np.isfinite(kmv_out["DTD"]).all(), f"Non-finite DTD for {cid}"

    def test_ecl_output_structure(self, credit_df, segment_forecast, pd_rating_df):
        """ECL output has correct columns and ECL_Lifetime ≥ ECL_12M."""
        energy_clients = credit_df[credit_df["sector"] == "Energy"][
            "client_id"
        ].tolist()[:2]
        if not energy_clients:
            pytest.skip("No Energy clients in credit portfolio")

        for cid in energy_clients:
            row = credit_df[credit_df["client_id"] == cid].iloc[0]
            com_info = {
                "E0": float(row["market_cap"]) / 1e6,
                "r": float(row["risk_free_rate"]),
                "volE": float(row["vol_equity"]),
                "rating": str(row["rating"]),
            }
            if com_info["rating"] not in pd_rating_df["Rating"].values:
                continue

            kmv_out = run_kmv(com_info, segment_forecast, pd_rating_df)
            ecl_out = compute_ecl(kmv_out, exposure=1e3, r=float(row["risk_free_rate"]))

            assert "ECL_12M" in ecl_out.columns
            assert "ECL_Lifetime" in ecl_out.columns
            assert "SCENARIO" in ecl_out.columns
            assert not ecl_out["ECL_12M"].isna().all(), f"All ECL_12M NaN for {cid}"
            # ECL_Lifetime ≥ ECL_12M (lifetime covers longer horizon)
            non_null = ecl_out.dropna(subset=["ECL_12M", "ECL_Lifetime"])
            if not non_null.empty:
                assert (non_null["ECL_Lifetime"] >= non_null["ECL_12M"] - 1e-9).all(), (
                    f"ECL_Lifetime < ECL_12M for {cid}"
                )

    def test_full_end_to_end(self, credit_df, segment_forecast, pd_rating_df):
        """
        Full pipeline for all Energy clients, sharing one segment-level forecast:
          calibrate → forecast → KMV → ECL → assert output non-empty and valid.
        """
        energy_clients = credit_df[credit_df["sector"] == "Energy"][
            "client_id"
        ].tolist()
        if not energy_clients:
            pytest.skip("No Energy clients in credit portfolio")

        results = []
        for cid in energy_clients:
            row = credit_df[credit_df["client_id"] == cid].iloc[0]
            com_info = {
                "E0": float(row["market_cap"]) / 1e6,
                "r": float(row["risk_free_rate"]),
                "volE": float(row["vol_equity"]),
                "rating": str(row["rating"]),
            }
            if com_info["rating"] not in pd_rating_df["Rating"].values:
                continue

            try:
                kmv_out = run_kmv(com_info, segment_forecast, pd_rating_df)
                ecl_out = compute_ecl(
                    kmv_out, exposure=1e3, r=float(row["risk_free_rate"])
                )
                results.append({"client_id": cid, "n_ecl_rows": len(ecl_out)})
            except Exception as e:
                pytest.fail(f"Pipeline failed for client {cid}: {e}")

        assert results, "No Energy clients processed successfully"
        print(
            f"\n  Processed {len(results)} Energy clients through full KMV+ECL pipeline"
            " (shared segment-level forecast)"
        )
        for r in results:
            assert r["n_ecl_rows"] > 0, f"Empty ECL output for {r['client_id']}"


# ---------------------------------------------------------------------------
# TestMultiSegmentForecastRouting
# ---------------------------------------------------------------------------


class TestMultiSegmentForecastRouting:
    """
    Full round trip for the "run all segments, route per client" design:
    train one ElasticNet model per (Energy) subsector, score every model against
    the whole portfolio-wide macro_forecast_df (as run_forecast now does for a
    segmented calibration), then route each client to its own subsector's
    trajectory (as run_credit_analysis now does) and confirm clients in
    different subsectors get different KMV/ECL outputs.
    """

    @pytest.fixture(scope="class")
    def energy_subsector_forecasts(self, merged_df, macro_forecast_df):
        """{subsector: segment_forecast_df} for every Energy subsector, mirroring
        run_forecast's multi-segment branch (every segment scored against the same
        MEV-only table)."""
        df_energy = merged_df[merged_df["sector"] == "Energy"]
        subsectors = sorted(df_energy["subsector"].unique())
        assert len(subsectors) >= 2, "Need >=2 Energy subsectors for this test"

        macro = macro_forecast_df.copy()
        macro["YEAR"] = pd.to_datetime(macro["date"], dayfirst=False).dt.year

        forecasts = {}
        for subsector in subsectors:
            df_seg = df_energy[df_energy["subsector"] == subsector]
            models = {}
            for target in TARGETS:
                X = df_seg[FEATURES].values
                y = df_seg[target].values
                X_train, _, y_train, _ = train_test_split(
                    X, y, test_size=0.2, random_state=42
                )
                scaler = StandardScaler()
                Xt = scaler.fit_transform(X_train)
                plugin = ElasticNetPlugin()
                plugin.fit(Xt, y_train, ElasticNetParams(alpha=0.01))
                models[target] = (plugin, scaler)

            rows = []
            for scen in ["Baseline", "Adverse", "Severely Adverse"]:
                df_sc = macro[macro["scenario"] == scen].sort_values("YEAR")
                if df_sc.empty:
                    continue
                X_fc = df_sc[FEATURES].values
                preds = {}
                for target, (plugin, scaler) in models.items():
                    X_s = scaler.transform(X_fc)
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        preds[target] = plugin.predict(X_s)
                for i, (_, row) in enumerate(df_sc.iterrows()):
                    rows.append(
                        {
                            "YEAR": int(row["YEAR"]),
                            "SCENARIO": scen,
                            "Total_Asset": float(max(1.0, preds["total_assets"][i])),
                            "CL": float(max(0.1, preds["total_shortterm_debts"][i])),
                            "NonCL": float(max(0.1, preds["total_longterm_debts"][i])),
                        }
                    )
            forecasts[subsector] = pd.DataFrame(rows)

        return forecasts

    def test_segments_produce_different_trajectories(self, energy_subsector_forecasts):
        """Different subsectors' models must not all produce identical Total_Asset paths."""
        totals = {
            subsector: tuple(df.sort_values(["SCENARIO", "YEAR"])["Total_Asset"])
            for subsector, df in energy_subsector_forecasts.items()
        }
        distinct = set(totals.values())
        assert len(distinct) > 1, (
            "All Energy subsectors produced identical forecasts — routing would be a no-op"
        )

    def test_clients_routed_to_own_subsector_get_distinct_kmv_output(
        self, credit_df, fin_df, energy_subsector_forecasts, pd_rating_df
    ):
        """
        Route each Energy client to its own subsector's forecast (replicating
        run_credit_analysis._lookup_forecast) and confirm different subsectors'
        clients produce different DTD/PD trajectories, not one uniform result.
        """
        fin_meta = fin_df[["client_id", "sector", "subsector"]].drop_duplicates(
            subset=["client_id"]
        )
        energy_clients = credit_df[credit_df["sector"] == "Energy"][
            "client_id"
        ].tolist()
        assert len(energy_clients) >= 2

        dtd_by_client = {}
        for cid in energy_clients:
            credit_row = credit_df[credit_df["client_id"] == cid].iloc[0]
            com_info = {
                "E0": float(credit_row["market_cap"]) / 1e6,
                "r": float(credit_row["risk_free_rate"]),
                "volE": float(credit_row["vol_equity"]),
                "rating": str(credit_row["rating"]),
            }
            if com_info["rating"] not in pd_rating_df["Rating"].values:
                continue

            fin_row = fin_meta[fin_meta["client_id"] == cid]
            if fin_row.empty:
                continue
            subsector = fin_row.iloc[0]["subsector"]

            # Segment routing: exact subsector match (mirrors _resolve_segment_key)
            segment_forecast = energy_subsector_forecasts.get(subsector)
            if segment_forecast is None or segment_forecast["YEAR"].nunique() < 2:
                continue

            kmv_out = run_kmv(com_info, segment_forecast, pd_rating_df)
            dtd_by_client[cid] = tuple(
                round(v, 6) for v in kmv_out.sort_values(["SCENARIO", "YEAR"])["DTD"]
            )

        assert len(dtd_by_client) >= 2, "Need >=2 routed clients to compare"
        distinct_dtd = set(dtd_by_client.values())
        assert len(distinct_dtd) > 1, (
            f"All routed clients produced identical DTD trajectories: {dtd_by_client} "
            "— segment routing is not differentiating clients"
        )
