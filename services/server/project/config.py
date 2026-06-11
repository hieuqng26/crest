import os
from datetime import timedelta
from dotenv import load_dotenv
import urllib
from project.logger import get_logger

logger = get_logger(__name__)
# import redis

load_dotenv()


class Config:
    """Config class for Flask app"""
    SECRET_KEY = os.getenv("SECRET_KEY", "a311dd3cad98047b3b06d479bce3839de6d05114f84167db0bb34be81eb06d9a")  # secrets.token_hex()
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.getenv("PERMANENT_SESSION_LIFETIME", 10)))
    ALLOWED_ORIGINS = "*"

    # JWT
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "7688049fa6c6a355bae4a311b22df7b828c200f4ce002b9b30defdb5b35c316e")  # secrets.token_hex()
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 10)))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(minutes=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES", 10)))
    JWT_TOKEN_LOCATION = os.getenv('JWT_TOKEN_LOCATION', 'headers').split(",")
    JWT_COOKIE_SECURE = True

    # # Flask Session
    # SESSION_TYPE = 'redis'
    # SESSION_REDIS = redis.StrictRedis(host='redis', port=6379, db=1)
    # SESSION_USE_SIGNER = True  # To sign the session ID for security
    # SESSION_PERMANENT = False
    # SESSION_COOKIE_SECURE = False  # Recommended for HTTPS
    # SESSION_COOKIE_HTTPONLY = True  # Prevent JS access to session cookie
    # SESSION_COOKIE_SAMESITE = 'None'  # Mitigate CSRF
    # SESSION_COOKIE_SAMESITE = 'Strict'  # Mitigate CSRF


class TestingConfig(Config):
    ALLOWED_ORIGINS = "*"
    REDIS_URL = "redis://localhost:6379/0"
    REDIS_QUEUES = ['cem', 'physical', 'netzero']
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = True


class DevelopmentConfig(Config):
    ALLOWED_ORIGINS = "*"
    REDIS_USER = os.getenv('REDIS_USER', 'default')
    REDIS_PASSWORD = urllib.parse.quote(os.getenv('REDIS_PASSWORD', ''))
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = os.getenv('REDIS_PORT', '6379')
    REDIS_DB = os.getenv('REDIS_DB', '0')
    REDIS_URL = f"redis://{REDIS_USER}:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    REDIS_QUEUES = ['default']
    # SESSION_COOKIE_SAMESITE = 'Strict'

    # Main application database (for user info, results)
    mssql_server_main = os.getenv('APP_DB_SERVER', 'tcp:mssql,1433')
    mssql_database_main = os.getenv('APP_DB_DATABASE', 'esg_dev')
    mssql_username_main = os.getenv('APP_DB_APP_USERNAME', 'crst')
    mssql_password_main = os.getenv('APP_DB_APP_PASSWORD', 'Ey@2024!')

    params_main = urllib.parse.quote_plus(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={mssql_server_main};"
        f"DATABASE={mssql_database_main};"
        f"UID={mssql_username_main};"
        f"PWD={mssql_password_main};"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
    )

    SQLALCHEMY_DATABASE_URI = f"mssql+pyodbc:///?odbc_connect={params_main}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = True
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': int(os.getenv('APP_DB_POOL_SIZE', 5)),                             # Increase the pool size (default is 5)
        'max_overflow': int(os.getenv('APP_DB_MAX_OVERFLOW', 10)),                      # Allow more overflow connections (default is 10)
        'pool_timeout': int(os.getenv('APP_DB_POOL_TIMEOUT', 30)),                      # Increase timeout for acquiring a connection (default is 30 seconds)
        'pool_recycle': int(os.getenv('APP_DB_POOL_RECYCLE', 1800)),                    # Recycle connections after 30 minutes to avoid stale connections
        'pool_pre_ping': os.getenv('APP_DB_POOL_PRE_PING', 'True').lower() == 'true'    # Enable pre-ping to check connection health
    }

    # APM
    ELASTIC_APM = {
        'SERVICE_NAME': os.getenv('ELASTIC_APM_SERVICE_NAME', 'crst'),
        'SECRET_TOKEN': os.getenv('ELASTIC_APM_SECRET_TOKEN', 'supersecret'),
        'SERVER_URL': os.getenv('ELASTIC_APM_SERVER_URL'),
        'ENVIRONMENT': os.getenv('ELASTIC_APM_ENVIRONMENT', 'development'),
        'LOG_LEVEL': 'DEBUG',
        'DEBUG': True
    }


class ProductionConfig(Config):
    ALLOWED_ORIGINS = "*"
    REDIS_USER = os.getenv('REDIS_USER', 'default')
    REDIS_PASSWORD = urllib.parse.quote(os.getenv('REDIS_PASSWORD', ''))
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = os.getenv('REDIS_PORT', '6379')
    REDIS_DB = os.getenv('REDIS_DB', '0')
    REDIS_URL = f"redis://{REDIS_USER}:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    REDIS_QUEUES = ['default']
    # SESSION_COOKIE_SAMESITE = 'Strict'

    # Main application database (for user info, results)
    mssql_server_main = os.getenv('APP_DB_SERVER', 'tcp:mssql,1433')
    mssql_database_main = os.getenv('APP_DB_DATABASE', 'esg_prod')
    mssql_username_main = os.getenv('APP_DB_APP_USERNAME', 'crst')
    mssql_password_main = os.getenv('APP_DB_APP_PASSWORD', 'Ey@2024!')

    params_main = urllib.parse.quote_plus(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={mssql_server_main};"
        f"DATABASE={mssql_database_main};"
        f"UID={mssql_username_main};"
        f"PWD={mssql_password_main};"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
    )

    SQLALCHEMY_DATABASE_URI = f"mssql+pyodbc:///?odbc_connect={params_main}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': int(os.getenv('APP_DB_POOL_SIZE', 20)),                            # Increase the pool size (default is 5)
        'max_overflow': int(os.getenv('APP_DB_MAX_OVERFLOW', 30)),                      # Allow more overflow connections (default is 10)
        'pool_timeout': int(os.getenv('APP_DB_POOL_TIMEOUT', 30)),                      # Increase timeout for acquiring a connection (default is 30 seconds)
        'pool_recycle': int(os.getenv('APP_DB_POOL_RECYCLE', 3600)),                    # Recycle connections after 30 minutes to avoid stale connections
        'pool_pre_ping': os.getenv('APP_DB_POOL_PRE_PING', 'True').lower() == 'true',   # Enable pre-ping to check connection health
        'pool_reset_on_return': 'commit',                                               # Reset connections on return
        'connect_args': {
            'timeout': 30,
            'autocommit': True
        }
    }

    # APM
    ELASTIC_APM = {
        'SERVICE_NAME': os.getenv('ELASTIC_APM_SERVICE_NAME', 'crst'),
        'SECRET_TOKEN': os.getenv('ELASTIC_APM_SECRET_TOKEN', 'supersecret'),
        'SERVER_URL': os.getenv('ELASTIC_APM_SERVER_URL'),
        'ENVIRONMENT': os.getenv('ELASTIC_APM_ENVIRONMENT', 'production'),
        'LOG_LEVEL': 'INFO',
        'DEBUG': False
    }
