import numpy as np
from pydantic import BaseModel, Field
from sklearn.linear_model import LinearRegression as _OLS

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import (
    coefficient_inference,
    regression_diagnostics,
)


class LinearRegressionParams(BaseModel):
    fit_intercept: bool = Field(default=True)


class LinearRegressionPlugin(BaseMLModel):
    family = "regression"
    algorithm = "LinearRegression"
    param_schema = LinearRegressionParams

    def __init__(self):
        self._model: _OLS | None = None
        self._inference = None

    def fit(self, X, y, params: LinearRegressionParams) -> None:
        self._model = _OLS(fit_intercept=params.fit_intercept)
        self._model.fit(X, y)
        self._inference = coefficient_inference(
            X, y, self._model.coef_, self._model.intercept_, exact=True
        )

    def predict(self, X) -> np.ndarray:
        return self._model.predict(X)

    def diagnostics(self, X, y) -> dict:
        y_pred = self.predict(X)
        return regression_diagnostics(
            y, y_pred, self._model.coef_, self._model.intercept_, self._inference
        )
