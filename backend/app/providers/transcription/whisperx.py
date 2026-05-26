from .base import BaseTranscriptionProvider


class WhisperXUnavailableError(RuntimeError):
    """Raised while WhisperX support is reserved for future development."""


class WhisperXTranscriptionProvider(BaseTranscriptionProvider):
    """Future WhisperX provider placeholder.

    The runtime factory wraps this in a FasterWhisper fallback so existing
    deployments can opt into the future provider name without breaking jobs.
    """

    def transcribe(self, audio_path, source_language, min_speakers=None, max_speakers=None):
        raise WhisperXUnavailableError(
            "WhisperX transcription is not implemented in this build yet."
        )
