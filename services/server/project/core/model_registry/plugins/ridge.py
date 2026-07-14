import numpy as np
from pydantic import BaseModel, Field
from sklearn.linear_model import Ridge as _Ridge

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import (
    coefficient_inference,
    regression_diagnostics,
)


class RidgeParams(BaseModel):
    alpha: float = Field(default=1.0, gt=0)


class RidgePlugin(BaseMLModel):
    family = "regression"
    algorithm = "Ridge"
    param_schema = RidgeParams

    def __init__(self):
        self._model: _Ridge | None = None
        self._inference = None

    def fit(self, X, y, params: RidgeParams) -> None:
        self._model = _Ridge(alpha=params.alpha)
        self._model.fit(X, y)
        self._inference = coefficient_inference(
            X, y, self._model.coef_, self._model.intercept_, exact=False
        )

    def predict(self, X) -> np.ndarray:
        return self._model.predict(X)

    def diagnostics(self, X, y) -> dict:
        y_pred = self.predict(X)
        return regression_diagnostics(
            y, y_pred, self._model.coef_, self._model.intercept_, self._inference
        )
