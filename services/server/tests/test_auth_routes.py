def test_jwt_is_cookie_mode(app):
    assert app.config["JWT_TOKEN_LOCATION"] == ["cookies"]
    assert app.config["JWT_COOKIE_SAMESITE"] == "Strict"
    assert app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds() == 15 * 60
    assert app.config["JWT_REFRESH_TOKEN_EXPIRES"].total_seconds() == 12 * 60 * 60
