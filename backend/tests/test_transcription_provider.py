import os
from dataclasses import dataclass

import pytest

from app.providers.transcription import (
    BaseTranscriptionProvider,
    FallbackTranscriptionProvider,
    FasterWhisperTranscriptionProvider,
    TranscriptSegment,
    WhisperXTranscriptionProvider,
    WhisperXUnavailableError,
    get_transcription_provider,
    normalize_language,
)


@dataclass
class FakeWhisperSegment:
    start: float
    end: float
    text: str


class FakeWhisperModel:
    instances = []
    segments = []

    def __init__(self, model_size, device, compute_type, download_root):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.calls = []
        self.instances.append(self)

    def transcribe(self, audio_path, **kwargs):
        self.calls.append({"audio_path": audio_path, **kwargs})
        return iter(self.segments), object()


@pytest.fixture(autouse=True)
def clear_fake_model_cache():
    FakeWhisperModel.instances = []
    FakeWhisperModel.segments = []
    FasterWhisperTranscriptionProvider._model_cache.clear()
    yield
    FasterWhisperTranscriptionProvider._model_cache.clear()


def test_get_transcription_provider_defaults_to_faster_whisper(monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_PROVIDER", raising=False)

    provider = get_transcription_provider()

    assert isinstance(provider, FasterWhisperTranscriptionProvider)


def test_get_transcription_provider_can_select_faster_whisper(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "faster_whisper")

    provider = get_transcription_provider()

    assert isinstance(provider, FasterWhisperTranscriptionProvider)


def test_get_transcription_provider_can_select_whisperx(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "whisperx")

    provider = get_transcription_provider()

    assert isinstance(provider, FallbackTranscriptionProvider)
    assert isinstance(provider.primary, WhisperXTranscriptionProvider)
    assert isinstance(provider.fallback, FasterWhisperTranscriptionProvider)


def test_get_transcription_provider_rejects_mock_runtime_provider(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "mock")

    with pytest.raises(ValueError, match="test-only"):
        get_transcription_provider()


def test_get_transcription_provider_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "other")

    with pytest.raises(ValueError, match="Unknown TRANSCRIPTION_PROVIDER"):
        get_transcription_provider()


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("English", "en"),
        ("Spanish", "es"),
        ("french", "fr"),
        ("EN", "en"),
        ("made up language", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_language(label, expected):
    assert normalize_language(label) == expected


def test_faster_whisper_provider_converts_non_empty_segments(tmp_path):
    FakeWhisperModel.segments = [
        FakeWhisperSegment(0.0, 1.2, " Hello world "),
        FakeWhisperSegment(1.3, 2.0, "   "),
        FakeWhisperSegment(2.1, 3.0, "Second line"),
    ]
    provider = FasterWhisperTranscriptionProvider(
        model_size="tiny",
        device="cpu",
        compute_type="int8",
        beam_size=3,
        vad_filter=True,
        model_dir=tmp_path / "models",
        model_class=FakeWhisperModel,
    )

    segments = provider.transcribe(tmp_path / "audio.wav", "English")

    assert segments == [
        TranscriptSegment(start_time=0.0, end_time=1.2, text="Hello world"),
        TranscriptSegment(start_time=2.1, end_time=3.0, text="Second line"),
    ]
    assert len(FakeWhisperModel.instances) == 1
    assert FakeWhisperModel.instances[0].calls == [
        {
            "audio_path": str(tmp_path / "audio.wav"),
            "language": "en",
            "task": "transcribe",
            "beam_size": 3,
            "vad_filter": True,
            "word_timestamps": False,
        }
    ]


def test_faster_whisper_provider_caches_model_per_process(tmp_path):
    provider = FasterWhisperTranscriptionProvider(
        model_size="tiny",
        device="cpu",
        compute_type="int8",
        model_dir=tmp_path / "models",
        model_class=FakeWhisperModel,
    )
    FakeWhisperModel.segments = [FakeWhisperSegment(0, 1, "One")]

    provider.transcribe(tmp_path / "one.wav", "English")
    provider.transcribe(tmp_path / "two.wav", "English")

    assert len(FakeWhisperModel.instances) == 1


def test_faster_whisper_provider_raises_when_no_speech_segments(tmp_path):
    FakeWhisperModel.segments = [
        FakeWhisperSegment(0, 1, " "),
    ]
    provider = FasterWhisperTranscriptionProvider(
        model_dir=tmp_path / "models",
        model_class=FakeWhisperModel,
    )

    with pytest.raises(ValueError, match="did not detect any speech"):
        provider.transcribe(tmp_path / "silent.wav", "English")


def test_whisperx_provider_is_future_stub(tmp_path):
    provider = WhisperXTranscriptionProvider()

    with pytest.raises(WhisperXUnavailableError, match="not implemented"):
        provider.transcribe(tmp_path / "audio.wav", "English")


def test_fallback_provider_uses_fallback_when_primary_is_unavailable(tmp_path):
    class UnavailableProvider(BaseTranscriptionProvider):
        def transcribe(self, audio_path, source_language, min_speakers=None, max_speakers=None):
            raise WhisperXUnavailableError("not ready")

    class RecordingProvider(BaseTranscriptionProvider):
        def __init__(self):
            self.calls = []

        def transcribe(self, audio_path, source_language, min_speakers=None, max_speakers=None):
            self.calls.append(
                {
                    "audio_path": audio_path,
                    "source_language": source_language,
                    "min_speakers": min_speakers,
                    "max_speakers": max_speakers,
                }
            )
            return [TranscriptSegment(0.0, 1.0, "fallback")]

    fallback = RecordingProvider()
    provider = FallbackTranscriptionProvider(
        primary=UnavailableProvider(),
        fallback=fallback,
        unavailable_errors=(WhisperXUnavailableError,),
        provider_name="WhisperX",
    )

    segments = provider.transcribe(
        tmp_path / "audio.wav",
        "English",
        min_speakers=2,
        max_speakers=4,
    )

    assert segments == [TranscriptSegment(0.0, 1.0, "fallback")]
    assert fallback.calls == [
        {
            "audio_path": tmp_path / "audio.wav",
            "source_language": "English",
            "min_speakers": 2,
            "max_speakers": 4,
        }
    ]


@pytest.mark.skipif(
    os.getenv("RUN_WHISPER_TEST") != "1",
    reason="Set RUN_WHISPER_TEST=1 and WHISPER_TEST_AUDIO to run real model smoke test.",
)
def test_real_faster_whisper_smoke(tmp_path):
    audio_path = os.getenv("WHISPER_TEST_AUDIO")
    if not audio_path:
        pytest.skip("Set WHISPER_TEST_AUDIO to a small speech audio file.")

    provider = FasterWhisperTranscriptionProvider(
        model_size=os.getenv("WHISPER_TEST_MODEL_SIZE", "tiny"),
        device=os.getenv("WHISPER_DEVICE", "cpu"),
        compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
        model_dir=tmp_path / "models",
    )

    segments = provider.transcribe(audio_path, os.getenv("WHISPER_TEST_LANGUAGE", "English"))

    assert segments
