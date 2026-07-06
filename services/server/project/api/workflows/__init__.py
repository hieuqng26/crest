from flask import Blueprint

workflows = Blueprint("workflows", __name__)

from project.api.workflows import routes  # noqa: E402, F401
