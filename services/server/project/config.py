import os
import urllib.parse
from datetime import timedelta

from dotenv import load_dotenv

from project.logger import get_logger

logger = get_logger(__name__)

load_dotenv()


# ---------------------------------------------------------------------------
# Shared builders — Dev and Prod differ only in a handful of values, so the
# repeated Redis / MSSQL / MinIO / engine / APM blocks live here once.
# ---------------------------------------------------------------------------
def _redis_url() -> str:
    user = os.getenv("REDIS_USER", "default")
    password = urllib.parse.quote(os.getenv("REDIS_PASSWORD", ""))
    host = os.getenv("REDIS_HOST", "localhost")
    port = os.getenv("REDIS_PORT", "6379")
    db = os.getenv("REDIS_DB", "0")
    return f"redis://{user}:{password}@{host}:{port}/{db}"


def _mssql_uri(default_database: str) -> str:
    """Build the SQLAlchemy MSSQL URI from env.

    No secret has a baked-in default — an unset ``APP_DB_APP_PASSWORD`` yields
    an empty password (dev supplies it via env/.env.dev; prod is checked by
    :func:`validate_required_config` before the app boots).
    """
    params = urllib.parse.quote_plus(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.getenv('APP_DB_SERVER', 'tcp:mssql,1433')};"
        f"DATABASE={os.getenv('APP_DB_DATABASE', default_database)};"
        f"UID={os.getenv('APP_DB_APP_USERNAME', 'crst')};"
        f"PWD={os.getenv('APP_DB_APP_PASSWORD', '')};"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
    )
    return f"mssql+pyodbc:///?odbc_connect={params}"


def _engine_options(
    *, pool_size: int, max_overflow: int, pool_recycle: int, extra=None
):
    opts = {
        "pool_size": int(os.getenv("APP_DB_POOL_SIZE", pool_size)),
        "max_overflow": int(os.getenv("APP_DB_MAX_OVERFLOW", max_overflow)),
        "pool_timeout": int(os.getenv("APP_DB_POOL_TIMEOUT", 30)),
        "pool_recycle": int(os.getenv("APP_DB_POOL_RECYCLE", pool_recycle)),
        "pool_pre_ping": os.getenv("APP_DB_POOL_PRE_PING", "True").lower() == "true",
    }
    if extra:
        opts.update(extra)
    return opts


def _minio_settings() -> dict:
    return {
        "MINIO_ENDPOINT": os.getenv("MINIO_ENDPOINT", "minio:9000"),
        "MINIO_ACCESS_KEY": os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        "MINIO_SECRET_KEY": os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        "MINIO_BUCKET": os.getenv("MINIO_BUCKET", "mst-artifacts"),
        "MINIO_SECURE": os.getenv("MINIO_SECURE", "false").lower() == "true",
    }


def _apm(environment: str, log_level: str, debug: bool) -> dict:
    return {
        "SERVICE_NAME": os.getenv("ELASTIC_APM_SERVICE_NAME", "crst"),
        "SECRET_TOKEN": os.getenv("ELASTIC_APM_SECRET_TOKEN"),
        "SERVER_URL": os.getenv("ELASTIC_APM_SERVER_URL"),
        "ENVIRONMENT": os.getenv("ELASTIC_APM_ENVIRONMENT", environment),
        "LOG_LEVEL": log_level,
        "DEBUG": debug,
    }


# Secrets that must be present when running under CONFIG_NAME=production —
# there are no safe defaults for these, so the app refuses to boot without them.
REQUIRED_PRODUCTION_SECRETS = (
    "SECRET_KEY",
    "JWT_SECRET_KEY",
    "APP_DB_APP_PASSWORD",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "REDIS_PASSWORD",
)


def validate_required_config(config_name: str | None) -> None:
    """Fail fast if a production deployment is missing a required secret.

    Called from ``create_app``. Only enforced for ``production`` — dev/testing
    keep convenient defaults.
    """
    if config_name != "production":
        return
    missing = [key for key in REQUIRED_PRODUCTION_SECRETS if not os.getenv(key)]
    if missing:
        raise RuntimeError(
            "Refusing to start: required production secrets are not set: "
            + ", ".join(missing)
        )


class Config:
    """Base config. Secrets have NO baked-in defaults — subclasses add
    dev-only conveniences; production supplies everything via the environment."""

    SECRET_KEY = os.getenv("SECRET_KEY")
    PERMANENT_SESSION_LIFETIME = timedelta(
        days=int(os.getenv("PERMANENT_SESSION_LIFETIME", 10))
    )

    CACHE_TYPE = "SimpleCache"  # overridden to RedisCache in Dev/Prod

    # Reject oversized request bodies with 413 before buffering/processing. A
    # generous ceiling (defense-in-depth behind nginx's client_max_body_size);
    # must stay above the largest legitimate dataset upload — tune per env.
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH_MB", 1024)) * 1024 * 1024

    # Rate limiting (flask-limiter). Storage is memory:// unless a URI is set
    # (Dev/Prod point it at Redis); per-route limits live on the endpoints.
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI")
    RATELIMIT_HEADERS_ENABLED = True
    # Limit for the auth endpoints (login/refresh/change-password).
    RATELIMIT_AUTH = os.getenv("RATELIMIT_AUTH", "10 per minute")

    # Demo/mock credit-risk data (mock_credit.py) is a dev/test convenience and
    # must never be reachable in production. Off by default; Dev/Testing enable it.
    ALLOW_MOCK_CREDIT = os.getenv("ALLOW_MOCK_CREDIT", "false").lower() == "true"

    # Seconds to cache a "session is valid" verdict before re-checking the DB.
    # In-app revocation invalidates the cache synchronously; this TTL only bounds
    # out-of-band (raw-DB) revocation latency. Kept short for a security control.
    SESSION_REVOCATION_CACHE_TTL = int(os.getenv("SESSION_REVOCATION_CACHE_TTL", 30))

    # JWT — cookie transport, revocable sessions
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")  # required; no baked-in default
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MIN", 15))
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        hours=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_H", 12))
    )
    JWT_TOKEN_LOCATION = ["cookies"]
    JWT_COOKIE_SAMESITE = "Strict"
    JWT_COOKIE_SECURE = os.getenv("JWT_COOKIE_SECURE", "true").lower() == "true"
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_ACCESS_COOKIE_PATH = "/api"
    JWT_REFRESH_COOKIE_PATH = "/api/auth/refresh"
    JWT_SESSION_COOKIE = False  # persist across browser restarts (until refresh expiry)


class TestingConfig(Config):
    SECRET_KEY = "test-secret"
    ALLOW_MOCK_CREDIT = True
    # Limiter stays wired (memory storage) but effectively unlimited so the
    # login-heavy suite never trips it; the rate-limit test lowers RATELIMIT_AUTH.
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_AUTH = "1000000 per hour"
    # Route exceptions through the global error boundary (as prod does) instead
    # of letting Flask re-raise them under TESTING — so integration tests see
    # the real DomainError/ValidationError -> HTTP status mapping.
    PROPAGATE_EXCEPTIONS = False
    REDIS_URL = "redis://localhost:6379/0"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = True
    JWT_SECRET_KEY = "test-secret"
    JWT_COOKIE_CSRF_PROTECT = False
    JWT_COOKIE_SECURE = False
    CACHE_TYPE = "SimpleCache"


class DevelopmentConfig(Config):
    # Dev-only fallback so a bare `flask run` works without an env file; prod
    # never inherits this (base Config.SECRET_KEY is None there).
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-secret-key")
    JWT_COOKIE_SECURE = os.getenv("JWT_COOKIE_SECURE", "false").lower() == "true"
    ALLOW_MOCK_CREDIT = os.getenv("ALLOW_MOCK_CREDIT", "true").lower() == "true"

    CACHE_TYPE = "RedisCache"
    REDIS_URL = _redis_url()
    CACHE_REDIS_URL = REDIS_URL
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI") or REDIS_URL
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL

    MINIO_ENDPOINT = _minio_settings()["MINIO_ENDPOINT"]
    MINIO_ACCESS_KEY = _minio_settings()["MINIO_ACCESS_KEY"]
    MINIO_SECRET_KEY = _minio_settings()["MINIO_SECRET_KEY"]
    MINIO_BUCKET = _minio_settings()["MINIO_BUCKET"]
    MINIO_SECURE = _minio_settings()["MINIO_SECURE"]

    SQLALCHEMY_DATABASE_URI = _mssql_uri(os.getenv("APP_DB_DATABASE", "esg_dev"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.getenv("APP_DB_ECHO", "False").lower() == "true"
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(
        pool_size=5, max_overflow=10, pool_recycle=1800
    )

    ELASTIC_APM = _apm("development", log_level="DEBUG", debug=True)


class ProductionConfig(Config):
    CACHE_TYPE = "RedisCache"
    REDIS_URL = _redis_url()
    CACHE_REDIS_URL = REDIS_URL
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI") or REDIS_URL
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL

    MINIO_ENDPOINT = _minio_settings()["MINIO_ENDPOINT"]
    MINIO_ACCESS_KEY = _minio_settings()["MINIO_ACCESS_KEY"]
    MINIO_SECRET_KEY = _minio_settings()["MINIO_SECRET_KEY"]
    MINIO_BUCKET = _minio_settings()["MINIO_BUCKET"]
    MINIO_SECURE = _minio_settings()["MINIO_SECURE"]

    SQLALCHEMY_DATABASE_URI = _mssql_uri(os.getenv("APP_DB_DATABASE", "esg_prod"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(
        pool_size=20,
        max_overflow=30,
        pool_recycle=3600,
        extra={
            "pool_reset_on_return": "commit",
            "connect_args": {"timeout": 30, "autocommit": True},
        },
    )

    ELASTIC_APM = _apm("production", log_level="INFO", debug=False)
