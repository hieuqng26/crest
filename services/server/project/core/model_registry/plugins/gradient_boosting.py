import numpy as np
from pydantic import BaseModel, Field
from sklearn.ensemble import GradientBoostingClassifier as _GBC

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import classification_diagnostics


class GradientBoostingParams(BaseModel):
    n_estimators: int = Field(default=100, ge=10)
    learning_rate: float = Field(default=0.1, gt=0)
    max_depth: int = Field(default=3, ge=1)


class GradientBoostingPlugin(BaseMLModel):
    family = "classification"
    algorithm = "GradientBoosting"
    param_schema = GradientBoostingParams

    def __init__(self):
        self._model: _GBC | None = None

    def fit(self, X, y, params: GradientBoostingParams) -> None:
        self._model = _GBC(
            n_estimators=params.n_estimators,
            learning_rate=params.learning_rate,
            max_depth=params.max_depth,
        )
        self._model.fit(X, y)

    def predict(self, X) -> np.ndarray:
        return self._model.predict_proba(X)[:, 1]

    def diagnostics(self, X, y) -> dict:
        y_prob = self.predict(X)
        return classification_diagnostics(y, y_prob, self._model, X)
