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


def _asr_model_size():
    explicit = os.getenv("WHISPER_MODEL_SIZE")
    if explicit:
        return explicit
    preset = os.getenv("ASR_QUALITY_PRESET", "balanced").strip().lower()
    return {
        "fast": "base",
        "balanced": "small",
        "accurate": "medium",
        "gpu-accurate": "large-v3",
    }.get(preset, "small")


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

    ASR_QUALITY_PRESET = os.getenv("ASR_QUALITY_PRESET", "balanced")
    WHISPER_MODEL_SIZE = _asr_model_size()
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
    WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    WHISPER_MODEL_DIR = Path(os.getenv("WHISPER_MODEL_DIR", STORAGE_DIR / "models"))
    WHISPERX_BATCH_SIZE = int(os.getenv("WHISPERX_BATCH_SIZE", "16"))
    WHISPERX_DIARIZE = _bool_env("WHISPERX_DIARIZE", False)
    WHISPER_MODEL_CACHE_SIZE = int(os.getenv("WHISPER_MODEL_CACHE_SIZE", "1"))
    WHISPERX_JA_ALIGN_MODEL = os.getenv(
        "WHISPERX_JA_ALIGN_MODEL", "jonatasgrosman/wav2vec2-large-xlsr-53-japanese"
    )
    WHISPERX_JA_ALIGN_REVISION = os.getenv(
        "WHISPERX_JA_ALIGN_REVISION", "2785e99ab97df77a32b5bd0ece5c9fa188a02f19"
    )
    WHISPERX_JA_REQUIRE_SAFETENSORS = _bool_env("WHISPERX_JA_REQUIRE_SAFETENSORS", True)
    WHISPERX_ALIGNMENT_FAILURE_MODE = os.getenv("WHISPERX_ALIGNMENT_FAILURE_MODE", "fallback")
    HF_TOKEN = os.getenv("HF_TOKEN", "")

    TRANSLATION_PROVIDER = os.getenv("TRANSLATION_PROVIDER", "routed")
    LIBRETRANSLATE_URL = os.getenv("LIBRETRANSLATE_URL", "http://localhost:5001")
    LIBRETRANSLATE_API_KEY = os.getenv("LIBRETRANSLATE_API_KEY", "")
    TRANSLATION_TIMEOUT_SECONDS = float(os.getenv("TRANSLATION_TIMEOUT_SECONDS", "30"))
    LOCAL_MT_MODEL = os.getenv("LOCAL_MT_MODEL", "facebook/nllb-200-distilled-600M")
    LOCAL_MT_MODEL_REVISION = os.getenv(
        "LOCAL_MT_MODEL_REVISION", "b3bbac6cd67efa90e0fcbe4c882ec79cfd782a17"
    )
    LOCAL_MT_REQUIRE_SAFETENSORS = _bool_env("LOCAL_MT_REQUIRE_SAFETENSORS", True)
    LOCAL_MT_MODEL_DIR = Path(os.getenv(
        "LOCAL_MT_MODEL_DIR", STORAGE_DIR / "models" / "nllb-200-distilled-600M-ct2"
    ))
    LOCAL_MT_TOKENIZER_DIR = Path(os.getenv(
        "LOCAL_MT_TOKENIZER_DIR", STORAGE_DIR / "models" / "nllb-200-distilled-600M-tokenizer"
    ))
    LOCAL_MT_DEVICE = os.getenv("LOCAL_MT_DEVICE", "cpu")
    LOCAL_MT_COMPUTE_TYPE = os.getenv("LOCAL_MT_COMPUTE_TYPE", "int8")
    LOCAL_MT_BATCH_SIZE = int(os.getenv("LOCAL_MT_BATCH_SIZE", "4"))
    LOCAL_MT_BEAM_SIZE = int(os.getenv("LOCAL_MT_BEAM_SIZE", "4"))
    LOCAL_MT_MAX_INPUT_TOKENS = int(os.getenv("LOCAL_MT_MAX_INPUT_TOKENS", "512"))
    LOCAL_MT_TOKENIZER_CACHE_SIZE = int(os.getenv("LOCAL_MT_TOKENIZER_CACHE_SIZE", "8"))
    TRANSLATION_DEFAULT_PROVIDER = os.getenv("TRANSLATION_DEFAULT_PROVIDER", "nllb-ct2")
    TRANSLATION_ROUTE_OVERRIDES = os.getenv(
        "TRANSLATION_ROUTE_OVERRIDES", "ja>en=libretranslate,fr>en=libretranslate"
    )

    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "")
    LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
    LLM_RETRIES = int(os.getenv("LLM_RETRIES", "1"))
    LLM_JSON_MODE = _bool_env("LLM_JSON_MODE", False)
    TRANSLATION_UNIT_MAX_SECONDS = float(os.getenv("TRANSLATION_UNIT_MAX_SECONDS", "12"))
    SOURCE_RECONSTRUCTION_MAX_GAP_SECONDS = float(
        os.getenv("SOURCE_RECONSTRUCTION_MAX_GAP_SECONDS", "0.2")
    )
    SOURCE_RECONSTRUCTION_MAX_FRAGMENT_CHARS = int(
        os.getenv("SOURCE_RECONSTRUCTION_MAX_FRAGMENT_CHARS", "2")
    )
    SOURCE_REVIEW_CONFIDENCE_THRESHOLD = float(
        os.getenv("SOURCE_REVIEW_CONFIDENCE_THRESHOLD", "0.45")
    )
    CAPTION_MAX_DURATION_SECONDS = float(
        os.getenv("CAPTION_MAX_DURATION_SECONDS", "6")
    )
    CAPTION_MAX_CHARS = int(os.getenv("CAPTION_MAX_CHARS", "84"))
    CAPTION_LINE_CHARS = int(os.getenv("CAPTION_LINE_CHARS", "42"))
    CAPTION_PAUSE_SECONDS = float(os.getenv("CAPTION_PAUSE_SECONDS", "0.65"))

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
