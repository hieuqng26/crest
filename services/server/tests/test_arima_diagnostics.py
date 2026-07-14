"""ARIMA diagnostics: per-term inference, information criteria, and the residual
/ stationarity test battery emitted by ``ARIMAPlugin``.

Pure numeric test (no Flask/DB)."""

import warnings

import numpy as np
import pytest

from project.core.model_registry.plugins.arima import ARIMAParams, ARIMAPlugin


@pytest.fixture()
def integrated_series():
    """A random-walk-plus-AR series that genuinely needs one difference."""
    rng = np.random.default_rng(21)
    n = 250
    innov = np.zeros(n)
    for t in range(1, n):
        innov[t] = 0.6 * innov[t - 1] + rng.normal()
    return np.cumsum(innov)


def test_arima_emits_coef_table_and_stats(integrated_series):
    y = integrated_series
    plugin = ARIMAPlugin()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # statsmodels optimiser chatter
        plugin.fit(None, y, ARIMAParams(p=1, d=1, q=1))
        diag = plugin.diagnostics(np.arange(5), y)

    # AR/MA terms with per-term p-values (sigma² is excluded).
    ct = diag["coef_table"]
    names = {r["feature"] for r in ct}
    assert names == {"ar.L1", "ma.L1"}
    for row in ct:
        assert row["p_value"] is not None and row["std_err"] is not None

    s = diag["arima_stats"]
    for key in ("aic", "bic", "hqic", "log_likelihood"):
        assert s[key] is not None
    assert s["order"] == [1, 1, 1]
    # Residual + stationarity tests are all populated.
    for key in ("ljung_box", "jarque_bera", "heteroskedasticity", "adf_test"):
        assert s[key] is not None
        assert "p_value" in s[key]
    assert s["ljung_box"]["lags"] == 10
    assert s["adf_test"]["n_diff"] == 1


def test_arima_residuals_available_for_qq(integrated_series):
    y = integrated_series
    plugin = ARIMAPlugin()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plugin.fit(None, y, ARIMAParams(p=1, d=1, q=1))
        diag = plugin.diagnostics(np.arange(5), y)
    assert isinstance(diag["residuals"], list) and len(diag["residuals"]) > 0
