from flask import Blueprint

segmentation_configs = Blueprint("segmentation_configs", __name__)

from . import routes  # noqa: F401, E402
