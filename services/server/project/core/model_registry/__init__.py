from project.core.model_registry.base import BaseMLModel
from project.core.model_registry.plugins.arima import ARIMAPlugin
from project.core.model_registry.plugins.elastic_net import ElasticNetPlugin
from project.core.model_registry.plugins.glm_binomial import GLMBinomialPlugin
from project.core.model_registry.plugins.gradient_boosting import GradientBoostingPlugin
from project.core.model_registry.plugins.lasso import LassoPlugin
from project.core.model_registry.plugins.linear_regression import LinearRegressionPlugin
from project.core.model_registry.plugins.logistic_regression import (
    LogisticRegressionPlugin,
)
from project.core.model_registry.plugins.random_forest import RandomForestPlugin
from project.core.model_registry.plugins.ridge import RidgePlugin
from project.core.model_registry.plugins.svm import SVMPlugin

REGISTRY: dict[str, type[BaseMLModel]] = {
    # Classification
    "LogisticRegression": LogisticRegressionPlugin,
    "GLM_Binomial": GLMBinomialPlugin,
    "SVM": SVMPlugin,
    # Ensemble
    "GradientBoosting": GradientBoostingPlugin,
    "RandomForest": RandomForestPlugin,
    # Regression
    "LinearRegression": LinearRegressionPlugin,
    "Ridge": RidgePlugin,
    "Lasso": LassoPlugin,
    "ElasticNet": ElasticNetPlugin,
    # Time Series
    "ARIMA": ARIMAPlugin,
}


def get_model_class(algorithm: str) -> type[BaseMLModel]:
    if algorithm not in REGISTRY:
        raise KeyError(f"Unknown algorithm: '{algorithm}'. Available: {list(REGISTRY)}")
    return REGISTRY[algorithm]


def registry_metadata() -> list[dict]:
    """Return algorithm metadata for the /registry endpoint."""
    out = []
    for name, cls in REGISTRY.items():
        schema = cls.param_schema.model_json_schema()
        params = []
        for field_name, field in cls.param_schema.model_fields.items():
            info = schema.get("properties", {}).get(field_name, {})
            params.append(
                {
                    "name": field_name,
                    "type": _json_type(info),
                    "default": field.default,
                    "description": info.get("description", field_name),
                }
            )
        out.append({"algorithm": name, "family": cls.family, "params": params})
    return out


def _json_type(prop: dict) -> str:
    t = prop.get("type", "string")
    if t == "number":
        return "float"
    if t == "integer":
        return "int"
    if t == "boolean":
        return "bool"
    return "string"
