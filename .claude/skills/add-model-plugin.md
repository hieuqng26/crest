# Skill: Add a model-registry plugin

To add a new calibratable algorithm.

## Steps
1. Create a class subclassing `BaseMLModel` (`project/core/model_registry/base.py`)
   implementing `fit()`, `predict()`, `diagnostics()`.
2. Define a Pydantic `BaseModel` param schema — required. No raw `**kwargs`.
3. Register it in the `REGISTRY` dict in
   `project/core/model_registry/__init__.py` under its family comment block
   (Classification / Ensemble / Regression / Time Series).
4. Ensure `diagnostics()` returns the metrics required for the algorithm's family
   (classification vs time-series vs statistical — mirror the metrics already returned
   by an existing plugin in the same family).
5. `ruff check . --exclude migrations --fix && ruff format . --exclude migrations`.

## Hard rule
Never mutate an existing plugin class in a way that breaks already-serialised pickles
in MinIO — calibrated runs load their pickle to predict/diagnose. If behavior must
change, add a NEW plugin version and register it under a new key.
