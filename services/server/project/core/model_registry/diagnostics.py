import numpy as np
from scipy.stats import (
    chi2,
    f as sp_f,
    jarque_bera as sp_jarque_bera,
    kurtosis as sp_kurtosis,
    skew as sp_skew,
    t as sp_t,
)
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from statsmodels.stats.diagnostic import het_breuschpagan, het_white
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson, omni_normtest


def _finite(v):
    """JSON-safe scalar: round floats, map NaN/inf → None."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return round(v, 6)


def _test(stat, p_value, *, passed):
    """A named hypothesis-test result, or None if it couldn't be computed."""
    p = _finite(p_value)
    if p is None:
        return None
    return {"stat": _finite(stat), "p_value": p, "passed": bool(passed)}


@np.errstate(all="ignore")
def compute_vif(X):
    """Variance Inflation Factor per feature (design-only, so exact for every
    estimator). Returns a list aligned with ``X``'s columns; entries that can't
    be computed (singular / degenerate) are ``None``. VIF > 5 warrants caution,
    > 10 signals serious multicollinearity.
    """
    try:
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] < 2:
            return None
        design = np.column_stack([np.ones(len(X)), X])
        out = []
        for j in range(X.shape[1]):
            try:
                out.append(_finite(variance_inflation_factor(design, j + 1)))
            except Exception:
                out.append(None)
        return out
    except Exception:
        return None


def _info_criteria(rss, n, k):
    """Gaussian log-likelihood and the AIC/BIC it implies. ``k`` counts all
    estimated parameters — coefficients + intercept + error variance (``p + 2``
    for a p-feature regression), matching statsmodels' OLS convention."""
    if rss <= 0 or n <= 0:
        return {"log_likelihood": None, "aic": None, "bic": None}
    llf = -0.5 * n * (np.log(2 * np.pi) + np.log(rss / n) + 1)
    return {
        "log_likelihood": _finite(llf),
        "aic": _finite(2 * k - 2 * llf),
        "bic": _finite(k * np.log(n) - 2 * llf),
    }


def _anova(ss_total, rss, p, df_resid):
    """Regression ANOVA decomposition: model vs residual sums of squares."""
    ss_model = ss_total - rss
    ms_model = ss_model / p if p > 0 else None
    ms_resid = rss / df_resid if df_resid > 0 else None
    f_stat = ms_model / ms_resid if (ms_model and ms_resid and ms_resid > 0) else None
    f_pvalue = float(sp_f.sf(f_stat, p, df_resid)) if f_stat is not None else None
    return {
        "ss_model": _finite(ss_model),
        "ss_resid": _finite(rss),
        "ss_total": _finite(ss_total),
        "df_model": int(p),
        "df_resid": int(df_resid),
        "ms_model": _finite(ms_model),
        "ms_resid": _finite(ms_resid),
        "f_stat": _finite(f_stat),
        "f_pvalue": _finite(f_pvalue),
    }


def _residual_normality(resid):
    """Skewness, excess kurtosis, and the Omnibus (D'Agostino–Pearson) normality
    test on the residuals. Complements the Jarque–Bera test."""
    out = {"skew": _finite(sp_skew(resid)), "kurtosis": _finite(sp_kurtosis(resid))}
    try:
        omni_stat, omni_p = omni_normtest(resid)
        out["omnibus"] = _test(omni_stat, omni_p, passed=omni_p > 0.05)
    except Exception:
        out["omnibus"] = None
    return out


def _white_test(resid, design):
    """White's general test for heteroscedasticity (needs squares + cross terms,
    so it can fail when features are many relative to n → None)."""
    try:
        lm, lm_p, _, _ = het_white(resid, design)
        return _test(lm, lm_p, passed=lm_p > 0.05)
    except Exception:
        return None


@np.errstate(all="ignore")
def _reset_test(y, design, y_pred):
    """Ramsey RESET for functional-form misspecification: does adding powers of
    the fitted values (ŷ², ŷ³) significantly improve the linear fit? Fitted via
    OLS on the design (restricted) vs the design augmented with ŷ powers (full),
    then an F-test on the two added terms."""
    try:
        n = len(y)
        yhat = np.asarray(y_pred, dtype=float).ravel()
        # Guard against degenerate powers (constant / exploding scale).
        aug = np.column_stack([design, yhat**2, yhat**3])
        k_r, k_f = design.shape[1], aug.shape[1]
        q = k_f - k_r
        df_resid_f = n - k_f
        if q <= 0 or df_resid_f <= 0:
            return None
        rss_r = float(
            np.sum((y - design @ np.linalg.lstsq(design, y, rcond=None)[0]) ** 2)
        )
        rss_f = float(np.sum((y - aug @ np.linalg.lstsq(aug, y, rcond=None)[0]) ** 2))
        if rss_f <= 0 or rss_r < rss_f:
            return None
        f_stat = ((rss_r - rss_f) / q) / (rss_f / df_resid_f)
        f_p = float(sp_f.sf(f_stat, q, df_resid_f))
        return _test(f_stat, f_p, passed=f_p > 0.05)
    except Exception:
        return None


@np.errstate(all="ignore")
def coefficient_inference(X, y, coef, intercept, *, exact: bool = True):
    """OLS-style inference for a fitted linear model, evaluated on the *training*
    design matrix ``X`` (the data the model was fit on).

    Returns ``(per_feature, regression_stats)`` where ``per_feature`` is a list of
    ``{std_err, t_stat, p_value, ci_lower, ci_upper}`` dicts aligned with ``coef``
    order, and ``regression_stats`` bundles the overall F-test, the intercept row,
    and residual assumption tests (Durbin–Watson, Jarque–Bera, Breusch–Pagan) plus
    the design condition number.

    For OLS (``exact=True``) these are exact; for the regularised estimators
    (Lasso/Ridge/ElasticNet) they are the OLS approximation applied to the shrunk
    coefficients — surfaced with ``exact_inference=False`` so the UI can caveat it.

    Returns ``(None, None)`` on any numerical failure — inference sits on the
    calibration job's critical path and must never raise.
    """
    try:
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float).ravel()
        if X.ndim != 2:
            return None, None
        n, p = X.shape
        df_resid = n - (p + 1)  # + intercept
        if p == 0 or df_resid <= 0:
            return None, None

        design = np.column_stack([np.ones(n), X])
        beta = np.concatenate(
            [[float(intercept)], np.asarray(coef, dtype=float).ravel()]
        )
        resid = y - design @ beta
        rss = float(resid @ resid)
        sigma2 = rss / df_resid

        cov = sigma2 * np.linalg.pinv(design.T @ design)
        se = np.sqrt(np.clip(np.diag(cov), 0.0, None))
        with np.errstate(divide="ignore", invalid="ignore"):
            t_stat = np.where(se > 0, beta / se, np.nan)
        p_value = 2.0 * sp_t.sf(np.abs(t_stat), df_resid)
        t_crit = float(sp_t.ppf(0.975, df_resid))
        ci_lower = beta - t_crit * se
        ci_upper = beta + t_crit * se

        def _row(i):
            return {
                "std_err": _finite(se[i]),
                "t_stat": _finite(t_stat[i]),
                "p_value": _finite(p_value[i]),
                "ci_lower": _finite(ci_lower[i]),
                "ci_upper": _finite(ci_upper[i]),
            }

        per_feature = [_row(i + 1) for i in range(p)]

        # Per-feature multicollinearity (design-only → exact for every estimator).
        vif = compute_vif(X)
        if vif is not None:
            for row, v in zip(per_feature, vif):
                row["vif"] = v

        # Overall significance (F-test on training R²) + adjusted R².
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - rss / ss_tot if ss_tot > 0 else 0.0
        adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / df_resid if df_resid > 0 else None
        if r2 < 1.0:
            f_stat = (r2 / p) / ((1.0 - r2) / df_resid)
            f_pvalue = float(sp_f.sf(f_stat, p, df_resid))
        else:
            f_stat = f_pvalue = None

        # Residual assumption / specification tests.
        dw = float(durbin_watson(resid))
        jb_stat, jb_p = sp_jarque_bera(resid)
        try:
            bp_lm, bp_p, _, _ = het_breuschpagan(resid, design)
            breusch_pagan = _test(bp_lm, bp_p, passed=bp_p > 0.05)
        except Exception:
            breusch_pagan = None

        regression_stats = {
            "n_obs": int(n),
            "n_features": int(p),
            "df_resid": int(df_resid),
            "r2_train": _finite(r2),
            "adj_r2": _finite(adj_r2),
            "sigma": _finite(np.sqrt(sigma2)),
            "exact_inference": bool(exact),
            "f_stat": _finite(f_stat),
            "f_pvalue": _finite(f_pvalue),
            "condition_number": _finite(np.linalg.cond(design)),
            "intercept_stats": {"coef": _finite(beta[0]), **_row(0)},
            "anova": _anova(ss_tot, rss, p, df_resid),
            **_info_criteria(rss, n, p + 2),
            **_residual_normality(resid),
            "durbin_watson": _finite(dw),
            "jarque_bera": _test(jb_stat, jb_p, passed=jb_p > 0.05),
            "breusch_pagan": breusch_pagan,
            "white_test": _white_test(resid, design),
            "reset_test": _reset_test(y, design, design @ beta),
        }
        return per_feature, regression_stats
    except Exception:
        return None, None


def regression_diagnostics(y, y_pred, coef, intercept, inference=None) -> dict:
    """Shared diagnostics for all regression plugins (OLS, Lasso, ElasticNet, Ridge).

    ``inference`` is the ``(per_feature, regression_stats)`` tuple from
    :func:`coefficient_inference` (computed at fit time on training data). When
    supplied, the per-feature stats are merged into ``coef_table`` and the overall
    stats are exposed under ``regression_stats``.
    """
    resid = y - y_pred
    r2 = float(r2_score(y, y_pred))
    mae = float(mean_absolute_error(y, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y, y_pred)))

    nonzero = y != 0
    mape = (
        float(np.mean(np.abs(resid[nonzero] / y[nonzero])) * 100)
        if nonzero.any()
        else None
    )

    coef_table = [{"feature": f"f{i}", "coef": float(c)} for i, c in enumerate(coef)]

    result = {
        "r2": r2,
        "mae": mae,
        "rmse": rmse,
        **({"mape": mape} if mape is not None else {}),
        "intercept": float(intercept),
        "coef_table": coef_table,
        "fitted": [round(float(v), 6) for v in y_pred],
        "residuals": [round(float(r), 6) for r in resid],
    }

    if inference is not None:
        per_feature, regression_stats = inference
        if per_feature is not None and len(per_feature) == len(coef_table):
            for base, stats in zip(coef_table, per_feature):
                base.update(stats)
            result["regression_stats"] = regression_stats

    return result


def classification_diagnostics(y, y_prob, model, X) -> dict:
    y_pred = (y_prob >= 0.5).astype(int)
    cm = confusion_matrix(y, y_pred)
    auc = float(roc_auc_score(y, y_prob))
    fpr, tpr, _ = roc_curve(y, y_prob)
    ks = float(np.max(tpr - fpr))
    gini = 2 * auc - 1

    frac_pos, mean_pred = calibration_curve(y, y_prob, n_bins=10, strategy="quantile")

    # Hosmer-Lemeshow
    n_bins = 10
    sorted_idx = np.argsort(y_prob)
    bins = np.array_split(sorted_idx, n_bins)
    hl_stat = 0.0
    for b in bins:
        obs = y[b].sum()
        exp = y_prob[b].sum()
        n = len(b)
        if exp > 0 and (n - exp) > 0:
            hl_stat += (obs - exp) ** 2 / exp + (n - obs - (n - exp)) ** 2 / (n - exp)
    hl_p = float(1 - chi2.cdf(hl_stat, df=n_bins - 2))

    fi = []
    if model is not None and hasattr(model, "feature_importances_"):
        scores = model.feature_importances_
        fi = [
            {"feature": f"f{i}", "importance": float(s)} for i, s in enumerate(scores)
        ]
    elif model is not None and hasattr(model, "coef_"):
        scores = np.abs(model.coef_[0]) if model.coef_.ndim > 1 else np.abs(model.coef_)
        total = scores.sum() or 1.0
        fi = [
            {"feature": f"f{i}", "importance": float(s / total)}
            for i, s in enumerate(scores)
        ]

    return {
        "auc_roc": auc,
        "ks": ks,
        "gini": float(gini),
        "accuracy": float(accuracy_score(y, y_pred)),
        "precision": float(precision_score(y, y_pred, zero_division=0)),
        "recall": float(recall_score(y, y_pred, zero_division=0)),
        "f1": float(f1_score(y, y_pred, zero_division=0)),
        "confusion_matrix": cm.tolist(),
        "roc_curve": {
            "fpr": [round(v, 4) for v in fpr.tolist()],
            "tpr": [round(v, 4) for v in tpr.tolist()],
        },
        "calibration_curve": {
            "fraction_positive": [round(v, 4) for v in frac_pos.tolist()],
            "mean_predicted": [round(v, 4) for v in mean_pred.tolist()],
        },
        "hosmer_lemeshow": {
            "stat": round(hl_stat, 4),
            "p_value": round(hl_p, 4),
            "passed": hl_p > 0.05,
        },
        "feature_importance": fi,
    }
