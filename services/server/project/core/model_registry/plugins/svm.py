import numpy as np
from pydantic import BaseModel, Field
from sklearn.svm import SVC as _SVC

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import classification_diagnostics


class SVMParams(BaseModel):
    C: float = Field(default=1.0, gt=0, description="Regularisation parameter")
    kernel: str = Field(default="rbf", description="rbf | linear | poly | sigmoid")
    gamma: str = Field(default="scale", description="scale | auto")


class SVMPlugin(BaseMLModel):
    family = "classification"
    algorithm = "SVM"
    param_schema = SVMParams

    def __init__(self):
        self._model: _SVC | None = None

    def fit(self, X, y, params: SVMParams) -> None:
        self._model = _SVC(
            C=params.C,
            kernel=params.kernel,
            gamma=params.gamma,
            probability=True,
            random_state=42,
        )
        self._model.fit(X, y)

    def predict(self, X) -> np.ndarray:
        return self._model.predict_proba(X)[:, 1]

    def diagnostics(self, X, y) -> dict:
        y_prob = self.predict(X)
        return classification_diagnostics(y, y_prob, None, X)
