import os
import re
from dataclasses import dataclass

from flask import current_app, has_app_context


_LANGUAGE_CODES = {
    "arabic": "ar",
    "ar": "ar",
    "chinese": "zh",
    "zh": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-hant": "zh",
    "zh-tw": "zh",
    "dutch": "nl",
    "nl": "nl",
    "english": "en",
    "en": "en",
    "french": "fr",
    "fr": "fr",
    "german": "de",
    "de": "de",
    "hindi": "hi",
    "hi": "hi",
    "italian": "it",
    "it": "it",
    "japanese": "ja",
    "ja": "ja",
    "korean": "ko",
    "ko": "ko",
    "portuguese": "pt",
    "pt": "pt",
    "pt-br": "pt",
    "pt-pt": "pt",
    "russian": "ru",
    "ru": "ru",
    "spanish": "es",
    "es": "es",
}

_LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")


@dataclass(frozen=True)
class TranscriptWord:
    text: str
    start_time: float | None = None
    end_time: float | None = None
    speaker_label: str | None = None
    confidence: float | None = None
    timing_quality: str = "forced_aligned"
    reconstruction_method: str = "raw"
    source_was_reconstructed: bool = False


@dataclass(frozen=True)
class TranscriptSegment:
    """Provider-neutral transcription result used by processing tasks."""

    start_time: float
    end_time: float
    text: str
    speaker_label: str | None = None
    words: tuple[TranscriptWord, ...] = ()
    timing_quality: str = "forced_aligned"


class BaseTranscriptionProvider:
    """Interface for speech-to-text implementations."""

    def check_ready(self, deep=False, load_models=False, diarize=None):
        """Return a provider-specific diagnostic readiness result."""
        raise NotImplementedError

    def transcribe(self, audio_path, source_language, min_speakers=None, max_speakers=None, glossary=None, diarize=None):
        """Return ordered timestamped transcript segments for an audio file."""
        raise NotImplementedError


def normalize_language(source_language):
    """Normalize common language labels to Whisper language codes."""
    if not source_language:
        return None
    normalized = str(source_language).strip().lower().replace("_", "-")
    known_code = _LANGUAGE_CODES.get(normalized)
    if known_code:
        return known_code
    if normalized == "auto":
        return None
    if _LANGUAGE_CODE_PATTERN.fullmatch(normalized):
        return normalized
    return None


def get_setting(name, default):
    """Read provider config from Flask config first, then the environment."""
    if has_app_context() and name in current_app.config:
        return current_app.config[name]
    return os.getenv(name, default)


def coerce_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
