import numpy as np
import statsmodels.api as sm
from pydantic import BaseModel, Field
from scipy.stats import chi2

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import (
    classification_diagnostics,
    compute_vif,
)


class GLMBinomialParams(BaseModel):
    fit_intercept: bool = Field(default=True)


class GLMBinomialPlugin(BaseMLModel):
    family = "statistical"
    algorithm = "GLM_Binomial"
    param_schema = GLMBinomialParams

    def __init__(self):
        self._result = None
        self._fit_intercept = True
        self._X_train = None

    def fit(self, X, y, params: GLMBinomialParams) -> None:
        self._fit_intercept = params.fit_intercept
        self._X_train = np.asarray(X, dtype=float)
        X_fit = sm.add_constant(X) if params.fit_intercept else X
        model = sm.GLM(y, X_fit, family=sm.families.Binomial())
        self._result = model.fit()

    def predict(self, X) -> np.ndarray:
        X_fit = sm.add_constant(X) if self._fit_intercept else X
        return self._result.predict(X_fit)

    def diagnostics(self, X, y) -> dict:
        res = self._result

        # Coefficient inference from the statsmodels Wald table. The constant is
        # split into intercept_stats (mirroring the regression convention) so the
        # feature rows stay 1:1 with feature_cols for the worker's name-patching.
        params_df = res.summary2().tables[1]
        rows = [
            {
                "name": str(name),
                "coef": float(row["Coef."]),
                "std_err": float(row["Std.Err."]),
                "z": float(row["z"]),
                "p_value": float(row["P>|z|"]),
                "ci_lower": float(row["[0.025"]),
                "ci_upper": float(row["0.975]"]),
            }
            for name, row in params_df.iterrows()
        ]

        _stat_keys = ("coef", "std_err", "z", "p_value", "ci_lower", "ci_upper")
        intercept_stats = None
        if self._fit_intercept and rows and rows[0]["name"] == "const":
            intercept_stats = {k: rows[0][k] for k in _stat_keys}
            rows = rows[1:]
        coef_table = [
            {"feature": r["name"], **{k: r[k] for k in _stat_keys}} for r in rows
        ]

        vif = compute_vif(self._X_train)
        if vif is not None and len(vif) == len(coef_table):
            for r, v in zip(coef_table, vif):
                r["vif"] = v

        # McFadden pseudo-R² and the likelihood-ratio test (full vs intercept-only).
        llf, llnull = float(res.llf), float(res.llnull)
        mcfadden = 1.0 - llf / llnull if llnull not in (0.0, None) else None
        lr_stat = float(res.null_deviance - res.deviance)
        lr_df = int(res.df_model)
        lr_p = float(chi2.sf(lr_stat, lr_df)) if lr_df > 0 else None

        y_pred = self.predict(X)
        clf_diag = classification_diagnostics(y, y_pred, None, X)

        glm_stats = {
            "n_obs": int(res.nobs),
            "df_model": lr_df,
            "aic": float(res.aic),
            "bic": float(res.bic_llf),
            "log_likelihood": llf,
            "deviance": float(res.deviance),
            "null_deviance": float(res.null_deviance),
            "pseudo_r2_mcfadden": mcfadden,
            "intercept_stats": intercept_stats,
            "lr_test": {
                "stat": lr_stat,
                "df": lr_df,
                "p_value": lr_p,
                "passed": bool(lr_p is not None and lr_p < 0.05),
            },
            "hosmer_lemeshow": clf_diag.get("hosmer_lemeshow"),
        }

        return {
            **clf_diag,
            # Flat keys kept for back-compat; glm_stats is the structured home.
            "aic": float(res.aic),
            "bic": float(res.bic_llf),
            "log_likelihood": llf,
            "deviance": float(res.deviance),
            "null_deviance": float(res.null_deviance),
            "coef_table": coef_table,
            "glm_stats": glm_stats,
        }
