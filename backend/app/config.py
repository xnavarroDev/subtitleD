import os
from pathlib import Path


def _bool_env(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _database_url():
    """Return a SQLAlchemy URL with local SQLite as the non-Docker fallback."""
    base_dir = Path(__file__).resolve().parents[1]
    default_sqlite = f"sqlite:///{base_dir / 'storage' / 'dev.db'}"
    url = os.getenv("DATABASE_URL", default_sqlite)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    """Runtime configuration loaded from environment variables.

    Docker Compose supplies Postgres and Redis URLs by default. The local
    fallbacks make utility tests and quick backend experiments work without the
    full stack.
    """

    BASE_DIR = Path(__file__).resolve().parents[1]
    STORAGE_DIR = Path(os.getenv("STORAGE_DIR", BASE_DIR / "storage"))

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

    WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    WHISPER_MODEL_DIR = Path(os.getenv("WHISPER_MODEL_DIR", STORAGE_DIR / "models"))
    WHISPERX_BATCH_SIZE = int(os.getenv("WHISPERX_BATCH_SIZE", "16"))
    WHISPERX_DIARIZE = _bool_env("WHISPERX_DIARIZE", True)
    HF_TOKEN = os.getenv("HF_TOKEN", "")

    TRANSLATION_PROVIDER = os.getenv("TRANSLATION_PROVIDER", "mock")
    LIBRETRANSLATE_URL = os.getenv("LIBRETRANSLATE_URL", "http://localhost:5001")
    LIBRETRANSLATE_API_KEY = os.getenv("LIBRETRANSLATE_API_KEY", "")
    TRANSLATION_TIMEOUT_SECONDS = float(os.getenv("TRANSLATION_TIMEOUT_SECONDS", "30"))

    DIAGNOSTICS_TIMEOUT_SECONDS = float(os.getenv("DIAGNOSTICS_TIMEOUT_SECONDS", "2"))
    DIAGNOSTICS_DEEP_CACHE_TTL_SECONDS = float(
        os.getenv("DIAGNOSTICS_DEEP_CACHE_TTL_SECONDS", "300")
    )
    WORKER_PING_TIMEOUT_SECONDS = float(os.getenv("WORKER_PING_TIMEOUT_SECONDS", "2"))
    WORKER_HEARTBEAT_INTERVAL_SECONDS = float(
        os.getenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", "5")
    )
    WORKER_HEARTBEAT_TTL_SECONDS = int(
        os.getenv("WORKER_HEARTBEAT_TTL_SECONDS", "15")
    )
    WORKER_HEARTBEAT_KEY_PREFIX = os.getenv(
        "WORKER_HEARTBEAT_KEY_PREFIX",
        "subtitled:workers:heartbeat:",
    )
    MIN_FREE_STORAGE_BYTES = int(
        os.getenv("MIN_FREE_STORAGE_BYTES", str(1024 * 1024 * 1024))
    )

    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ]

    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(2 * 1024 * 1024 * 1024)))
    CREATE_TABLES = os.getenv("CREATE_TABLES", "true").lower() == "true"
