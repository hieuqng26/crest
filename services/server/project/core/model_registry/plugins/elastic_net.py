import numpy as np
from pydantic import BaseModel, Field
from sklearn.linear_model import ElasticNet as _ElasticNet

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import (
    coefficient_inference,
    regression_diagnostics,
)


class ElasticNetParams(BaseModel):
    alpha: float = Field(
        default=1.0, gt=0, description="Overall regularisation strength"
    )
    l1_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="L1 mix ratio (0 = Ridge, 1 = Lasso)",
    )
    max_iter: int = Field(default=1000, ge=100)
    fit_intercept: bool = Field(default=True)


class ElasticNetPlugin(BaseMLModel):
    family = "regression"
    algorithm = "ElasticNet"
    param_schema = ElasticNetParams

    def __init__(self):
        self._model: _ElasticNet | None = None
        self._inference = None

    def fit(self, X, y, params: ElasticNetParams) -> None:
        self._model = _ElasticNet(
            alpha=params.alpha,
            l1_ratio=params.l1_ratio,
            max_iter=params.max_iter,
            fit_intercept=params.fit_intercept,
        )
        self._model.fit(X, y)
        self._inference = coefficient_inference(
            X, y, self._model.coef_, self._model.intercept_, exact=False
        )

    def predict(self, X) -> np.ndarray:
        return self._model.predict(X)

    def diagnostics(self, X, y) -> dict:
        y_pred = self.predict(X)
        diag = regression_diagnostics(
            y, y_pred, self._model.coef_, self._model.intercept_, self._inference
        )
        diag["n_nonzero_coef"] = int(np.sum(self._model.coef_ != 0))
        diag["l1_ratio"] = float(self._model.l1_ratio)
        return diag
