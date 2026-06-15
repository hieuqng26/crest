from flask import Blueprint

model_configs = Blueprint("model_configs", __name__)

from . import routes  # noqa: F401, E402
