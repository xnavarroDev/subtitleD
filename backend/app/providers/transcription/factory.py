from .base import get_setting
from .faster_whisper import FasterWhisperTranscriptionProvider
from .whisperx import WhisperXTranscriptionProvider


def get_transcription_provider():
    """Select the configured runtime transcription provider."""
    provider = str(get_setting("TRANSCRIPTION_PROVIDER", "faster_whisper")).strip().lower()
    if provider in {"", "faster_whisper", "faster-whisper", "whisper"}:
        return FasterWhisperTranscriptionProvider()
    if provider in {"whisperx", "whisper-x"}:
        return WhisperXTranscriptionProvider()
    if provider == "mock":
        raise ValueError(
            "Mock transcription is test-only. Use 'faster_whisper' or 'whisperx'."
        )
    raise ValueError("Unknown TRANSCRIPTION_PROVIDER. Use 'faster_whisper' or 'whisperx'.")
