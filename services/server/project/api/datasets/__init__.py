from flask import Blueprint

datasets = Blueprint('datasets', __name__)

from . import routes  # noqa: F401, E402
