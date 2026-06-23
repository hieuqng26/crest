from flask import jsonify

from project.api.auth import sessions


def register_http_error_handlers(app):
    @app.errorhandler(403)
    def _forbidden(e):
        return jsonify({"message": str(e.description)}), 403

    @app.errorhandler(404)
    def _not_found(e):
        return jsonify({"message": str(e.description)}), 404


def register_jwt_callbacks(jwt):
    @jwt.token_in_blocklist_loader
    def _check_revoked(jwt_header, jwt_payload):
        return sessions.is_revoked(jwt_payload.get("sid"))

    @jwt.revoked_token_loader
    def _revoked(jwt_header, jwt_payload):
        return (
            jsonify(
                {
                    "type": "Authentication Error",
                    "message": "Session expired or revoked",
                }
            ),
            401,
        )

    @jwt.unauthorized_loader
    def _missing(reason):
        return jsonify({"type": "Authentication Error", "message": reason}), 401

    @jwt.invalid_token_loader
    def _invalid(reason):
        return jsonify({"type": "Authentication Error", "message": reason}), 401

    @jwt.expired_token_loader
    def _expired(jwt_header, jwt_payload):
        return jsonify(
            {"type": "Authentication Error", "message": "Token expired"}
        ), 401
