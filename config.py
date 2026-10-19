"""Application configuration.

Secrets come from environment variables (or a local .env file), never from
source code that is committed to Git.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# python-dotenv loads the private .env file if it is installed.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover - depends on the local environment
    pass


def _int_from_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Config:
    """Settings shared by every environment."""

    # Minutes ahead of UTC for the customer's local time (330 = India, UTC+5:30).
    # Used to decide whether an appointment date or time is already in the past.
    BOOKING_UTC_OFFSET_MINUTES = _int_from_env("BOOKING_UTC_OFFSET_MINUTES", 330)

    # A fixed fallback is acceptable for local development only.
    # ProductionConfig refuses to start without a real SECRET_KEY.
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-secret-do-not-use-in-production"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    TESTING = False
    DEBUG = False

    # Database. A relative SQLite path such as sqlite:///fixnear.db is stored
    # inside the project's "instance" folder (which Git ignores).
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///fixnear.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(Config):
    DEBUG = os.environ.get("FLASK_DEBUG") == "1"


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    # Never touch the real database in tests. The test helpers point this at a
    # temporary file; this in-memory default is only a safety net.
    SQLALCHEMY_DATABASE_URI = "sqlite://"


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True  # cookies only travel over HTTPS


_CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config():
    """Pick a config class from the APP_ENV environment variable."""
    name = os.environ.get("APP_ENV", "development").lower()
    config_class = _CONFIGS.get(name, DevelopmentConfig)
    if config_class is ProductionConfig:
        if not os.environ.get("SECRET_KEY"):
            raise RuntimeError("SECRET_KEY must be set when APP_ENV=production.")
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError("DATABASE_URL must be set when APP_ENV=production.")
    return config_class
