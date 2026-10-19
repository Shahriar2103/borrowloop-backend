"""Application configuration, read from environment variables (.env is loaded automatically)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-change-me-please-32b")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRES_HOURS = int(os.getenv("JWT_EXPIRES_HOURS", "24"))

    # DB_MODE: "auto"  -> use MongoDB if reachable, otherwise in-memory mongomock
    #          "mongo" -> require a real MongoDB server
    #          "mock"  -> always use the in-memory database
    DB_MODE = os.getenv("DB_MODE", "auto")
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "borrowloop")
    MONGO_TIMEOUT_MS = int(os.getenv("MONGO_TIMEOUT_MS", "2000"))

    # Load data/seed/*.json automatically when the users collection is empty.
    AUTO_SEED = _bool("AUTO_SEED", True)
    SEED_DIR = str(BASE_DIR / "data" / "seed")

    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100

    TESTING = False
    DEBUG = _bool("FLASK_DEBUG", False)


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    DB_MODE = "mock"
    MONGO_DB_NAME = "borrowloop_test"
    AUTO_SEED = True
    JWT_EXPIRES_HOURS = 1


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(name=None):
    name = name or os.getenv("APP_ENV", "development")
    return CONFIGS.get(name, DevelopmentConfig)
