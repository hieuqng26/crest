"""Coefficient inference + assumption tests emitted by the regression plugins.

Pure numeric tests (no Flask/DB) covering the ``coefficient_inference`` helper
and the enriched ``coef_table`` / ``regression_stats`` that back the Diagnosis &
Backtesting tab.
"""

import numpy as np
import pytest

from project.core.model_registry.diagnostics import (
    coefficient_inference,
    regression_diagnostics,
)
from project.core.model_registry.plugins.elastic_net import (
    ElasticNetParams,
    ElasticNetPlugin,
)
from project.core.model_registry.plugins.lasso import LassoParams, LassoPlugin
from project.core.model_registry.plugins.linear_regression import (
    LinearRegressionParams,
    LinearRegressionPlugin,
)
from project.core.model_registry.plugins.ridge import RidgeParams, RidgePlugin


@pytest.fixture()
def linear_data():
    """y = 2 + 1.5·x0 − 0.8·x1 + 0·x2 + small noise; x2 is a null feature."""
    rng = np.random.default_rng(0)
    n = 240
    X = rng.normal(size=(n, 3))
    y = (
        2.0
        + 1.5 * X[:, 0]
        - 0.8 * X[:, 1]
        + 0.0 * X[:, 2]
        + rng.normal(scale=0.4, size=n)
    )
    return X, y


def test_ols_inference_recovers_significance(linear_data):
    X, y = linear_data
    from sklearn.linear_model import LinearRegression

    m = LinearRegression().fit(X, y)
    per_feature, stats = coefficient_inference(X, y, m.coef_, m.intercept_, exact=True)

    assert per_feature is not None and len(per_feature) == 3
    # Real predictors are highly significant; the null feature is not.
    assert per_feature[0]["p_value"] < 0.01
    assert per_feature[1]["p_value"] < 0.01
    assert per_feature[2]["p_value"] > 0.05
    # 95% CI must bracket the point estimate.
    for i, row in enumerate(per_feature):
        assert row["ci_lower"] <= m.coef_[i] <= row["ci_upper"]

    assert stats["exact_inference"] is True
    assert stats["f_pvalue"] < 1e-6
    assert 0.0 <= stats["r2_train"] <= 1.0
    for key in ("durbin_watson", "condition_number", "jarque_bera", "breusch_pagan"):
        assert stats[key] is not None
    assert "coef" in stats["intercept_stats"] and "p_value" in stats["intercept_stats"]


def test_extended_regression_stats_present_and_consistent(linear_data):
    X, y = linear_data
    from sklearn.linear_model import LinearRegression

    m = LinearRegression().fit(X, y)
    _, stats = coefficient_inference(X, y, m.coef_, m.intercept_, exact=True)

    # Information criteria + adjusted R² are present and sane.
    assert stats["adj_r2"] is not None and stats["adj_r2"] <= stats["r2_train"]
    for key in ("log_likelihood", "aic", "bic", "skew", "kurtosis"):
        assert stats[key] is not None
    # BIC penalises harder than AIC for this n.
    assert stats["bic"] > stats["aic"]

    # ANOVA decomposition: SS_model + SS_resid == SS_total and its F reconciles
    # with the top-level F-statistic.
    a = stats["anova"]
    assert a["ss_model"] + a["ss_resid"] == pytest.approx(a["ss_total"], rel=1e-4)
    assert a["f_stat"] == pytest.approx(stats["f_stat"], rel=1e-3)

    # Specification / normality tests computed (well-specified data → all pass).
    for key in ("omnibus", "white_test", "reset_test"):
        assert stats[key] is not None
        assert stats[key]["passed"] is True


def test_vif_flags_collinearity():
    rng = np.random.default_rng(7)
    n = 300
    x0 = rng.normal(size=n)
    x1 = rng.normal(size=n)
    x2 = x0 + rng.normal(scale=0.01, size=n)  # near-duplicate of x0
    X = np.column_stack([x0, x1, x2])
    y = 1.0 + x0 - 0.5 * x1 + rng.normal(scale=0.3, size=n)
    from sklearn.linear_model import LinearRegression

    m = LinearRegression().fit(X, y)
    per_feature, _ = coefficient_inference(X, y, m.coef_, m.intercept_, exact=True)
    vifs = [row["vif"] for row in per_feature]
    # The collinear pair (x0, x2) has huge VIF; the independent x1 stays near 1.
    assert vifs[0] > 10 and vifs[2] > 10
    assert vifs[1] < 5


def test_regression_diagnostics_merges_inference(linear_data):
    X, y = linear_data
    from sklearn.linear_model import LinearRegression

    m = LinearRegression().fit(X, y)
    inference = coefficient_inference(X, y, m.coef_, m.intercept_, exact=True)
    diag = regression_diagnostics(y, m.predict(X), m.coef_, m.intercept_, inference)

    assert "regression_stats" in diag
    for row in diag["coef_table"]:
        assert {"coef", "std_err", "t_stat", "p_value", "ci_lower", "ci_upper"} <= set(
            row
        )


def test_regression_diagnostics_without_inference_omits_stats(linear_data):
    X, y = linear_data
    from sklearn.linear_model import LinearRegression

    m = LinearRegression().fit(X, y)
    diag = regression_diagnostics(y, m.predict(X), m.coef_, m.intercept_)
    assert "regression_stats" not in diag
    assert all("p_value" not in row for row in diag["coef_table"])


def test_inference_guards_degenerate_shapes():
    # Fewer observations than parameters → no valid inference, no exception.
    X = np.ones((2, 3))
    y = np.array([1.0, 2.0])
    assert coefficient_inference(X, y, np.zeros(3), 0.0) == (None, None)
    # Zero features.
    assert coefficient_inference(
        np.empty((5, 0)), np.arange(5.0), np.array([]), 0.0
    ) == (
        None,
        None,
    )


@pytest.mark.parametrize(
    "Plugin,Params,kwargs,exact",
    [
        (LinearRegressionPlugin, LinearRegressionParams, {}, True),
        (ElasticNetPlugin, ElasticNetParams, {"alpha": 0.1}, False),
        (LassoPlugin, LassoParams, {"alpha": 0.05}, False),
        (RidgePlugin, RidgeParams, {"alpha": 1.0}, False),
    ],
)
def test_plugins_emit_enriched_diagnostics(linear_data, Plugin, Params, kwargs, exact):
    X, y = linear_data
    Xtr, Xval, ytr, yval = X[:180], X[180:], y[:180], y[180:]
    plugin = Plugin()
    plugin.fit(Xtr, ytr, Params(**kwargs))
    diag = plugin.diagnostics(Xval, yval)

    assert "qq_data" not in diag  # replaced by client-side QQ from residuals
    assert len(diag["residuals"]) == len(yval)
    stats = diag["regression_stats"]
    assert stats["exact_inference"] is exact
    assert stats["n_features"] == 3
    # Every coefficient row carries inference + VIF aligned to the features.
    assert len(diag["coef_table"]) == 3
    for row in diag["coef_table"]:
        assert row["p_value"] is not None
        assert row["vif"] is not None
    # The extended battery is emitted for every regression estimator.
    for key in ("adj_r2", "aic", "bic", "anova", "omnibus", "white_test", "reset_test"):
        assert key in stats
