import numpy as np
from pydantic import BaseModel, Field
from sklearn.linear_model import LogisticRegression as _LR

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import classification_diagnostics


class LogisticRegressionParams(BaseModel):
    C: float = Field(default=1.0, gt=0)
    max_iter: int = Field(default=200, ge=10)
    solver: str = Field(default="lbfgs")


class LogisticRegressionPlugin(BaseMLModel):
    family = "classification"
    algorithm = "LogisticRegression"
    param_schema = LogisticRegressionParams

    def __init__(self):
        self._model: _LR | None = None

    def fit(self, X, y, params: LogisticRegressionParams) -> None:
        self._model = _LR(C=params.C, max_iter=params.max_iter, solver=params.solver)
        self._model.fit(X, y)

    def predict(self, X) -> np.ndarray:
        return self._model.predict_proba(X)[:, 1]

    def diagnostics(self, X, y) -> dict:
        y_prob = self.predict(X)
        return classification_diagnostics(y, y_prob, self._model, X)
