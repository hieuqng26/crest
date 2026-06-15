from abc import ABC, abstractmethod
from typing import Any

import numpy as np


class BaseMLModel(ABC):
    """
    All ML plugins must inherit this class and implement fit/predict/diagnostics.
    family and algorithm are declared as class-level attributes.
    param_schema must be a Pydantic BaseModel subclass.
    """

    family: str  # 'classification' | 'timeseries' | 'statistical'
    algorithm: str  # e.g. 'LogisticRegression'
    param_schema: type  # Pydantic model

    @abstractmethod
    def fit(self, X: Any, y: Any, params: Any) -> None:
        """Fit the model. params is a validated Pydantic instance."""
        ...

    @abstractmethod
    def predict(self, X: Any) -> np.ndarray:
        """Return predictions for X."""
        ...

    @abstractmethod
    def diagnostics(self, X: Any, y: Any) -> dict:
        """Compute and return a dict of evaluation metrics."""
        ...
