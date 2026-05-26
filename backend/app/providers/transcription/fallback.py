from flask import current_app, has_app_context

from .base import BaseTranscriptionProvider


class FallbackTranscriptionProvider(BaseTranscriptionProvider):
    """Try an optional provider and fall back to FasterWhisper when unavailable."""

    def __init__(self, primary, fallback, unavailable_errors, provider_name):
        self.primary = primary
        self.fallback = fallback
        self.unavailable_errors = tuple(unavailable_errors)
        self.provider_name = provider_name

    def transcribe(self, audio_path, source_language, min_speakers=None, max_speakers=None):
        try:
            return self.primary.transcribe(
                audio_path,
                source_language,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )
        except self.unavailable_errors as exc:
            if has_app_context():
                current_app.logger.warning(
                    "%s unavailable; falling back to faster-whisper: %s",
                    self.provider_name,
                    exc,
                )
            return self.fallback.transcribe(
                audio_path,
                source_language,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )
