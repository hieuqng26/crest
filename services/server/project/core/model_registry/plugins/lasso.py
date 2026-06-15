import numpy as np
from pydantic import BaseModel, Field
from sklearn.linear_model import Lasso as _Lasso

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import regression_diagnostics


class LassoParams(BaseModel):
    alpha: float = Field(default=1.0, gt=0, description="L1 regularisation strength")
    max_iter: int = Field(default=1000, ge=100)
    fit_intercept: bool = Field(default=True)


class LassoPlugin(BaseMLModel):
    family = "regression"
    algorithm = "Lasso"
    param_schema = LassoParams

    def __init__(self):
        self._model: _Lasso | None = None

    def fit(self, X, y, params: LassoParams) -> None:
        self._model = _Lasso(
            alpha=params.alpha,
            max_iter=params.max_iter,
            fit_intercept=params.fit_intercept,
        )
        self._model.fit(X, y)

    def predict(self, X) -> np.ndarray:
        return self._model.predict(X)

    def diagnostics(self, X, y) -> dict:
        y_pred = self.predict(X)
        diag = regression_diagnostics(
            y, y_pred, self._model.coef_, self._model.intercept_
        )
        diag["n_nonzero_coef"] = int(np.sum(self._model.coef_ != 0))
        return diag
