import os
from contextlib import contextmanager

from flask import Flask, request
from flask_bcrypt import Bcrypt
from flask_caching import Cache
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from project.config import Config, DevelopmentConfig, ProductionConfig, TestingConfig
from project.logger import get_logger

logger = get_logger(__name__)

db = SQLAlchemy()
migrate = Migrate()
bcrypt = Bcrypt()
cache = Cache()
DATA_STORE = os.getenv("DATA_STORE", "/var/lib/app_data")


@contextmanager
def app_session():
    """Provide a transactional scope around a series of operations."""
    try:
        yield db.session
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        db.session.close()


def create_app():
    """Create a Flask app instance given a configuration class
    This allows us to create multiple instances of the app (dev, test, prod)
    """
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=4, x_host=4)
    app.config["WTF_CSRF_ENABLED"] = (
        os.getenv("WTF_CSRF_ENABLED", "FALSE").upper() == "TRUE"
    )
    app.config["WTF_CSRF_CHECK_DEFAULT"] = (
        os.getenv("WTF_CSRF_CHECK_DEFAULT", "FALSE").upper() == "TRUE"
    )
    csrf = CSRFProtect()
    csrf.init_app(app)

    # Choose the configuration
    if os.getenv("CONFIG_NAME") == "production":
        app.config.from_object(ProductionConfig)
        # allowed_origins = ProductionConfig.ALLOWED_ORIGINS.split(',')
    elif os.getenv("CONFIG_NAME") == "development":
        app.config.from_object(DevelopmentConfig)
        # allowed_origins = DevelopmentConfig.ALLOWED_ORIGINS.split(',')
    elif os.getenv("CONFIG_NAME") == "testing":
        app.config.from_object(TestingConfig)
        # allowed_origins = TestingConfig.ALLOWED_ORIGINS.split(',')
    else:
        app.config.from_object(Config)
        # allowed_origins = Config.ALLOWED_ORIGINS.split(',')

    # cookies
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"

    # Configure CORS, actually not set here, but set at after_request()
    allowed_origins = []
    CORS(
        app,
        supports_credentials=True,
        resources={r"/api/*": {"origins": allowed_origins}},
    )

    # JWT
    app.config["JWT_SECRET_KEY"] = Config.JWT_SECRET_KEY
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = Config.JWT_ACCESS_TOKEN_EXPIRES
    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = Config.JWT_REFRESH_TOKEN_EXPIRES
    app.config["JWT_TOKEN_LOCATION"] = Config.JWT_TOKEN_LOCATION
    jwt = JWTManager(app)

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    cache.init_app(
        app,
        config={"CACHE_TYPE": "RedisCache", "CACHE_REDIS_URL": app.config["REDIS_URL"]},
    )

    # Import models so Alembic autogenerate can detect them
    from project.api.auditlog.models import AuditLog  # noqa: F401
    from project.api.auditlog.routes import auditlog
    from project.api.auth.models import ActiveSession  # noqa: F401
    from project.api.auth.routes import auth
    from project.api.calibrations import calibrations
    from project.api.credit_risk import credit_risk
    from project.api.datasets import datasets
    from project.api.evaluations import evaluations
    from project.api.forecasts import forecasts
    from project.api.model_configs import model_configs
    from project.api.roles.models import Role  # noqa: F401
    from project.api.roles.routes import role
    from project.api.users.models import User  # noqa: F401
    from project.api.users.routes import user
    from project.db_models.calibration_models import (  # noqa: F401
        CalibrationRun,
        CalibrationRunLog,
        Dataset,
        Forecast,
        ModelConfig,
    )
    from project.db_models.credit_models import (
        CreditRiskResult,  # noqa: F401
        CreditRiskRun,  # noqa: F401
        CreditRiskRunLog,  # noqa: F401
        PdRating,  # noqa: F401
    )

    app.register_blueprint(auth, url_prefix="/api/auth")
    app.register_blueprint(user, url_prefix="/api/user")
    app.register_blueprint(auditlog, url_prefix="/api/log")
    app.register_blueprint(role, url_prefix="/api/role")
    app.register_blueprint(datasets, url_prefix="/api/datasets")
    app.register_blueprint(model_configs, url_prefix="/api/model-configs")
    app.register_blueprint(calibrations, url_prefix="/api/calibrations")
    app.register_blueprint(evaluations, url_prefix="/api/evaluations")
    app.register_blueprint(forecasts, url_prefix="/api/forecasts")
    app.register_blueprint(credit_risk, url_prefix="/api/credit-risk")

    # add health check route
    @app.route("/api/ping", methods=["GET"])
    def ping():
        return "pong", 200

    @app.after_request
    def after_request(response):
        allowed_origins_env = os.getenv("CORS_ORIGIN")
        allowed_origins = [s.strip() for s in allowed_origins_env.split(",")]
        origin = request.headers.get("Origin")
        if origin in allowed_origins:
            # use "set" instead of "add" to ensure only one origin
            response.headers.set("Access-Control-Allow-Origin", origin)
        response.headers.add(
            "Access-Control-Allow-Headers", "Content-Type, Authorization"
        )
        response.headers.add(
            "Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        )
        response.headers.add("Access-Control-Allow-Credentials", "true")

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content-Security-Policy
        csp_origin = origin if origin in allowed_origins else "'self'"
        # use "set" instead of "add" to ensure only one origin
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self' {csp_origin}; "
            f"script-src 'self' {csp_origin}; "
            f"style-src 'self' {csp_origin}; "
            f"img-src 'self' data: {csp_origin}; "
            f"font-src 'self' data: {csp_origin};"
        )

        # prevent cache
        response.headers["Cache-Control"] = "no-store"  # for modern browsers
        response.headers["Pragma"] = "no-cache"  # for old browsers

        # Strict transport security
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        return response

    return app
