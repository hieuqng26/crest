import numpy as np
from scipy.stats import chi2, norm as sp_norm
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


def regression_diagnostics(y, y_pred, coef, intercept) -> dict:
    """Shared diagnostics for all regression plugins (OLS, Lasso, ElasticNet, Ridge)."""
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

    n = len(resid)
    sorted_resid = np.sort(resid)
    theoretical_q = sp_norm.ppf((np.arange(1, n + 1) - 0.375) / (n + 0.25))

    return {
        "r2": r2,
        "mae": mae,
        "rmse": rmse,
        **({"mape": mape} if mape is not None else {}),
        "intercept": float(intercept),
        "coef_table": coef_table,
        "fitted": [round(float(v), 6) for v in y_pred],
        "residuals": [round(float(r), 6) for r in resid],
        "qq_data": {
            "theoretical": [round(float(v), 4) for v in theoretical_q.tolist()],
            "sample": [round(float(v), 4) for v in sorted_resid.tolist()],
        },
    }


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
