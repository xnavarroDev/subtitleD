import os
import sys
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


class FakeWhisperXModel:
    def __init__(self, module):
        self.module = module
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append({"audio": audio, **kwargs})
        self.module.transcribe_calls.append({"audio": audio, **kwargs})
        return {
            "language": "en",
            "segments": [
                {"start": 0.0, "end": 1.1, "text": " Hello world "},
                {"start": 1.2, "end": 2.0, "text": "   "},
            ],
        }


class FakeWhisperXModule:
    def __init__(self):
        self.load_audio_calls = []
        self.load_model_calls = []
        self.load_align_model_calls = []
        self.align_calls = []
        self.assign_word_speakers_calls = []
        self.transcribe_calls = []

    def load_audio(self, audio_path):
        self.load_audio_calls.append(audio_path)
        return "audio-array"

    def load_model(self, model_size, device, **kwargs):
        self.load_model_calls.append(
            {"model_size": model_size, "device": device, **kwargs}
        )
        return FakeWhisperXModel(self)

    def load_align_model(self, **kwargs):
        self.load_align_model_calls.append(kwargs)
        return "align-model", {"language": kwargs["language_code"]}

    def align(self, segments, model, metadata, audio, device, **kwargs):
        self.align_calls.append(
            {
                "segments": segments,
                "model": model,
                "metadata": metadata,
                "audio": audio,
                "device": device,
                **kwargs,
            }
        )
        return {
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.1,
                    "text": " Hello world ",
                    "words": [
                        {"word": "Hello", "speaker": "SPEAKER_00"},
                        {"word": "world", "speaker": "SPEAKER_00"},
                    ],
                },
                {"start": 1.2, "end": 2.0, "text": "   "},
                {
                    "start": 2.1,
                    "end": 3.0,
                    "text": "Second line",
                    "speaker": "SPEAKER_01",
                },
            ]
        }

    def assign_word_speakers(self, diarize_segments, result):
        self.assign_word_speakers_calls.append(
            {"diarize_segments": diarize_segments, "result": result}
        )
        return result


class FakeDiarizationPipeline:
    instances = []

    def __init__(self, use_auth_token, device):
        self.use_auth_token = use_auth_token
        self.device = device
        self.calls = []
        self.instances.append(self)

    def __call__(self, audio, **kwargs):
        self.calls.append({"audio": audio, **kwargs})
        return "diarize-segments"


@pytest.fixture(autouse=True)
def clear_fake_model_cache():
    FakeWhisperModel.instances = []
    FakeWhisperModel.segments = []
    FakeDiarizationPipeline.instances = []
    FasterWhisperTranscriptionProvider._model_cache.clear()
    WhisperXTranscriptionProvider._model_cache.clear()
    WhisperXTranscriptionProvider._align_model_cache.clear()
    yield
    FasterWhisperTranscriptionProvider._model_cache.clear()
    WhisperXTranscriptionProvider._model_cache.clear()
    WhisperXTranscriptionProvider._align_model_cache.clear()


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

    assert isinstance(provider, WhisperXTranscriptionProvider)


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


def test_whisperx_provider_transcribes_aligns_and_assigns_speakers(tmp_path):
    fake_whisperx = FakeWhisperXModule()
    provider = WhisperXTranscriptionProvider(
        model_size="tiny",
        device="cpu",
        compute_type="int8",
        batch_size=4,
        model_dir=tmp_path / "models",
        hf_token="secret",
        whisperx_module=fake_whisperx,
        diarization_pipeline_class=FakeDiarizationPipeline,
    )

    segments = provider.transcribe(
        tmp_path / "audio.wav",
        "English",
        min_speakers=2,
        max_speakers=3,
    )

    assert segments == [
        TranscriptSegment(
            start_time=0.0,
            end_time=1.1,
            text="Hello world",
            speaker_label="SPEAKER_00",
        ),
        TranscriptSegment(
            start_time=2.1,
            end_time=3.0,
            text="Second line",
            speaker_label="SPEAKER_01",
        ),
    ]
    assert fake_whisperx.load_audio_calls == [str(tmp_path / "audio.wav")]
    assert fake_whisperx.load_model_calls == [
        {
            "model_size": "tiny",
            "device": "cpu",
            "compute_type": "int8",
            "download_root": str(tmp_path / "models"),
            "language": "en",
        }
    ]
    assert fake_whisperx.transcribe_calls == [
        {
            "audio": "audio-array",
            "batch_size": 4,
            "language": "en",
            "task": "transcribe",
        }
    ]
    assert fake_whisperx.load_align_model_calls == [
        {
            "language_code": "en",
            "device": "cpu",
            "model_dir": str(tmp_path / "models"),
        }
    ]
    assert fake_whisperx.align_calls[0]["return_char_alignments"] is False
    assert len(FakeDiarizationPipeline.instances) == 1
    diarization = FakeDiarizationPipeline.instances[0]
    assert diarization.use_auth_token == "secret"
    assert diarization.device == "cpu"
    assert diarization.calls == [
        {
            "audio": "audio-array",
            "min_speakers": 2,
            "max_speakers": 3,
        }
    ]
    assert fake_whisperx.assign_word_speakers_calls


def test_whisperx_provider_can_skip_diarization_without_token(tmp_path):
    fake_whisperx = FakeWhisperXModule()
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=False,
        hf_token="",
        whisperx_module=fake_whisperx,
    )

    segments = provider.transcribe(tmp_path / "audio.wav", "English")

    assert segments[0].speaker_label == "SPEAKER_00"
    assert fake_whisperx.assign_word_speakers_calls == []
    assert FakeDiarizationPipeline.instances == []


def test_whisperx_provider_requires_hf_token_for_diarization(tmp_path):
    fake_whisperx = FakeWhisperXModule()
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=True,
        hf_token="",
        whisperx_module=fake_whisperx,
    )

    with pytest.raises(RuntimeError, match="HF_TOKEN"):
        provider.transcribe(tmp_path / "audio.wav", "English")


def test_whisperx_provider_reports_missing_optional_install(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "whisperx", None)
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=False,
    )

    with pytest.raises(WhisperXUnavailableError, match="requirements-whisperx"):
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
