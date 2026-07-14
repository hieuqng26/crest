"""GLM logistic diagnostics: coefficient Wald tests, VIF, McFadden pseudo-R²,
and the likelihood-ratio test emitted by ``GLMBinomialPlugin``.

Pure numeric test (no Flask/DB)."""

import numpy as np
import pytest

from project.core.model_registry.plugins.glm_binomial import (
    GLMBinomialParams,
    GLMBinomialPlugin,
)


@pytest.fixture()
def binary_data():
    """logit(p) = 0.5 + 1.2·x0 − 0.9·x1 + 0·x2; x2 is a null predictor."""
    rng = np.random.default_rng(11)
    n = 500
    X = rng.normal(size=(n, 3))
    lin = 0.5 + 1.2 * X[:, 0] - 0.9 * X[:, 1]
    p = 1.0 / (1.0 + np.exp(-lin))
    y = (rng.uniform(size=n) < p).astype(int)
    return X, y


def test_glm_emits_coefficient_and_fit_statistics(binary_data):
    X, y = binary_data
    plugin = GLMBinomialPlugin()
    plugin.fit(X, y, GLMBinomialParams())
    diag = plugin.diagnostics(X, y)

    # coef_table: one row per feature (the constant is split into glm_stats), each
    # with a Wald z / p-value and a VIF.
    ct = diag["coef_table"]
    assert len(ct) == 3
    for row in ct:
        for key in ("feature", "coef", "std_err", "z", "p_value", "vif"):
            assert key in row
    # Real predictors significant, null predictor not.
    assert ct[0]["p_value"] < 0.05 and ct[1]["p_value"] < 0.05
    assert ct[2]["p_value"] > 0.05
    # Independent design → VIFs near 1.
    assert all(row["vif"] < 5 for row in ct)

    gs = diag["glm_stats"]
    assert 0.0 < gs["pseudo_r2_mcfadden"] < 1.0
    assert gs["intercept_stats"] is not None and "coef" in gs["intercept_stats"]
    # LR test: the fitted model is a large improvement over the intercept-only null.
    assert gs["lr_test"]["p_value"] < 1e-6
    assert gs["lr_test"]["passed"] is True
    assert gs["lr_test"]["df"] == 3
    for key in ("aic", "bic", "log_likelihood", "deviance", "null_deviance"):
        assert gs[key] is not None


def test_glm_no_intercept_keeps_all_rows_as_features():
    rng = np.random.default_rng(12)
    n = 300
    X = rng.normal(size=(n, 2))
    y = (rng.uniform(size=n) < 1.0 / (1.0 + np.exp(-(X[:, 0] - X[:, 1])))).astype(int)
    plugin = GLMBinomialPlugin()
    plugin.fit(X, y, GLMBinomialParams(fit_intercept=False))
    diag = plugin.diagnostics(X, y)
    assert len(diag["coef_table"]) == 2
    assert diag["glm_stats"]["intercept_stats"] is None
