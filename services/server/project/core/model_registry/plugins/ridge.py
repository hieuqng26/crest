import numpy as np
from pydantic import BaseModel, Field
from sklearn.linear_model import Ridge as _Ridge

from project.core.model_registry.base import BaseMLModel


class RidgeParams(BaseModel):
    alpha: float = Field(default=1.0, gt=0)


class RidgePlugin(BaseMLModel):
    family = "regression"
    algorithm = "Ridge"
    param_schema = RidgeParams

    def __init__(self):
        self._model: _Ridge | None = None

    def fit(self, X, y, params: RidgeParams) -> None:
        self._model = _Ridge(alpha=params.alpha)
        self._model.fit(X, y)

    def predict(self, X) -> np.ndarray:
        return self._model.predict(X)

    def diagnostics(self, X, y) -> dict:
        y_pred = self.predict(X)
        resid = y - y_pred
        ss_res = float(np.sum(resid**2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        mae = float(np.mean(np.abs(resid)))
        rmse = float(np.sqrt(np.mean(resid**2)))
        coef = (
            self._model.coef_.tolist()
            if hasattr(self._model.coef_, "tolist")
            else list(self._model.coef_)
        )
        return {
            "r2": r2,
            "mae": mae,
            "rmse": rmse,
            "coefficients": coef,
            "intercept": float(self._model.intercept_),
            "residuals": resid.tolist(),
        }
