import numpy as np
from pydantic import BaseModel, Field
from sklearn.ensemble import RandomForestClassifier as _RFC

from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.diagnostics import classification_diagnostics


class RandomForestParams(BaseModel):
    n_estimators: int = Field(default=100, ge=10)
    max_depth: int | None = Field(default=None)
    min_samples_split: int = Field(default=2, ge=2)
    max_features: str = Field(default="sqrt", description="sqrt | log2 | auto")


class RandomForestPlugin(BaseMLModel):
    family = "ensemble"
    algorithm = "RandomForest"
    param_schema = RandomForestParams

    def __init__(self):
        self._model: _RFC | None = None

    def fit(self, X, y, params: RandomForestParams) -> None:
        self._model = _RFC(
            n_estimators=params.n_estimators,
            max_depth=params.max_depth,
            min_samples_split=params.min_samples_split,
            max_features=params.max_features,
            random_state=42,
        )
        self._model.fit(X, y)

    def predict(self, X) -> np.ndarray:
        return self._model.predict_proba(X)[:, 1]

    def diagnostics(self, X, y) -> dict:
        y_prob = self.predict(X)
        return classification_diagnostics(y, y_prob, self._model, X)
