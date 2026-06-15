from flask import Blueprint

calibrations = Blueprint("calibrations", __name__)

from . import routes  # noqa: F401, E402
