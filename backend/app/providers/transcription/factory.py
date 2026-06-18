from .whisperx import WhisperXTranscriptionProvider


def get_transcription_provider():
    """Return the runtime transcription provider."""
    return WhisperXTranscriptionProvider()
