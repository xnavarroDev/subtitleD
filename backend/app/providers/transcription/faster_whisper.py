from pathlib import Path

from .base import (
    BaseTranscriptionProvider,
    TranscriptSegment,
    coerce_bool,
    get_setting,
    normalize_language,
)


class FasterWhisperTranscriptionProvider(BaseTranscriptionProvider):
    """Local faster-whisper provider for timestamped speech-to-text."""

    _model_cache = {}

    def __init__(
        self,
        model_size=None,
        device=None,
        compute_type=None,
        beam_size=None,
        vad_filter=None,
        model_dir=None,
        model_class=None,
    ):
        self.model_size = model_size or get_setting("WHISPER_MODEL_SIZE", "base")
        self.device = device or get_setting("WHISPER_DEVICE", "cpu")
        self.compute_type = compute_type or get_setting("WHISPER_COMPUTE_TYPE", "int8")
        self.beam_size = int(
            beam_size if beam_size is not None else get_setting("WHISPER_BEAM_SIZE", 5)
        )
        self.vad_filter = coerce_bool(
            vad_filter if vad_filter is not None else get_setting("WHISPER_VAD_FILTER", True)
        )
        self.model_dir = Path(
            model_dir or get_setting("WHISPER_MODEL_DIR", Path("storage") / "models")
        )
        self.model_class = model_class

    def transcribe(self, audio_path, source_language, min_speakers=None, max_speakers=None):
        """Transcribe an audio file and return non-empty timestamped segments."""
        model = self._get_model()
        segments, _info = model.transcribe(
            str(audio_path),
            language=normalize_language(source_language),
            task="transcribe",
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            word_timestamps=False,
        )

        transcript_segments = []
        for segment in segments:
            text = (getattr(segment, "text", "") or "").strip()
            if not text:
                continue
            transcript_segments.append(
                TranscriptSegment(
                    start_time=float(getattr(segment, "start")),
                    end_time=float(getattr(segment, "end")),
                    text=text,
                )
            )

        if not transcript_segments:
            raise ValueError("Whisper did not detect any speech segments in the audio.")
        return transcript_segments

    def _get_model(self):
        model_class = self.model_class or _load_whisper_model_class()
        self.model_dir.mkdir(parents=True, exist_ok=True)
        cache_key = (
            model_class,
            self.model_size,
            self.device,
            self.compute_type,
            str(self.model_dir),
        )
        if cache_key not in self._model_cache:
            self._model_cache[cache_key] = model_class(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root=str(self.model_dir),
            )
        return self._model_cache[cache_key]


def _load_whisper_model_class():
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed. Install backend requirements.") from exc
    return WhisperModel
