from project.core.model_registry.base import BaseMLModel

# Maps algorithm name → plugin class.
# Populated as plugins are implemented in Phase 3.
REGISTRY: dict[str, type[BaseMLModel]] = {}


def get_model_class(algorithm: str) -> type[BaseMLModel]:
    if algorithm not in REGISTRY:
        raise KeyError(f"Unknown algorithm: '{algorithm}'. Available: {list(REGISTRY)}")
    return REGISTRY[algorithm]
