import numpy as np
import statsmodels.api as sm
from pydantic import BaseModel, Field

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import classification_diagnostics


class GLMBinomialParams(BaseModel):
    fit_intercept: bool = Field(default=True)


class GLMBinomialPlugin(BaseMLModel):
    family = "statistical"
    algorithm = "GLM_Binomial"
    param_schema = GLMBinomialParams

    def __init__(self):
        self._result = None
        self._fit_intercept = True

    def fit(self, X, y, params: GLMBinomialParams) -> None:
        self._fit_intercept = params.fit_intercept
        X_fit = sm.add_constant(X) if params.fit_intercept else X
        model = sm.GLM(y, X_fit, family=sm.families.Binomial())
        self._result = model.fit()

    def predict(self, X) -> np.ndarray:
        X_fit = sm.add_constant(X) if self._fit_intercept else X
        return self._result.predict(X_fit)

    def diagnostics(self, X, y) -> dict:

        params_df = self._result.summary2().tables[1]
        coef_table = []
        for name, row in params_df.iterrows():
            coef_table.append(
                {
                    "name": str(name),
                    "coef": float(row["Coef."]),
                    "std_err": float(row["Std.Err."]),
                    "z": float(row["z"]),
                    "p_value": float(row["P>|z|"]),
                    "ci_lower": float(row["[0.025"]),
                    "ci_upper": float(row["0.975]"]),
                }
            )
        y_pred = self.predict(X)
        clf_diag = classification_diagnostics(y, y_pred, None, X)
        return {
            **clf_diag,
            "aic": float(self._result.aic),
            "bic": float(self._result.bic),
            "log_likelihood": float(self._result.llf),
            "deviance": float(self._result.deviance),
            "null_deviance": float(self._result.null_deviance),
            "coef_table": coef_table,
        }
