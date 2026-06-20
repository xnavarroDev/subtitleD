import sys

import pytest

from app.providers.transcription import (
    TranscriptSegment,
    WhisperXTranscriptionProvider,
    WhisperXUnavailableError,
    get_transcription_provider,
    normalize_language,
)


class FakeWhisperXModel:
    def __init__(self, module):
        self.module = module
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append({"audio": audio, **kwargs})
        self.module.transcribe_calls.append({"audio": audio, **kwargs})
        return {
            "language": self.module.detected_language,
            "segments": self.module.transcribed_segments,
        }


class FakeWhisperXModule:
    def __init__(
        self,
        transcribed_segments=None,
        aligned_segments=None,
        detected_language="en",
    ):
        self.detected_language = detected_language
        self.transcribed_segments = (
            transcribed_segments
            if transcribed_segments is not None
            else [
                {"start": 0.0, "end": 1.1, "text": " Hello world "},
                {"start": 1.2, "end": 2.0, "text": "   "},
            ]
        )
        self.aligned_segments = (
            aligned_segments
            if aligned_segments is not None
            else [
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
        )
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
        return {"segments": self.aligned_segments}

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
    FakeDiarizationPipeline.instances = []
    WhisperXTranscriptionProvider._model_cache.clear()
    WhisperXTranscriptionProvider._align_model_cache.clear()
    yield
    WhisperXTranscriptionProvider._model_cache.clear()
    WhisperXTranscriptionProvider._align_model_cache.clear()


@pytest.mark.parametrize(
    "provider_env",
    [None, "", "whisperx", "faster_whisper", "mock", "other"],
)
def test_get_transcription_provider_always_returns_whisperx(monkeypatch, provider_env):
    if provider_env is None:
        monkeypatch.delenv("TRANSCRIPTION_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("TRANSCRIPTION_PROVIDER", provider_env)

    provider = get_transcription_provider()

    assert isinstance(provider, WhisperXTranscriptionProvider)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("English", "en"),
        ("Spanish", "es"),
        ("french", "fr"),
        ("EN", "en"),
        ("uk", "uk"),
        ("pt-br", "pt-br"),
        ("auto", None),
        ("made up language", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_language(label, expected):
    assert normalize_language(label) == expected


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


def test_whisperx_provider_quick_readiness_does_not_load_models(tmp_path):
    fake_whisperx = FakeWhisperXModule()
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=False,
        whisperx_module=fake_whisperx,
    )

    result = provider.check_ready(deep=False)

    assert result.status == "pass"
    assert fake_whisperx.load_model_calls == []


def test_whisperx_provider_deep_readiness_does_not_load_models(tmp_path, monkeypatch):
    fake_whisperx = FakeWhisperXModule()
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=True,
        hf_token="secret",
        whisperx_module=fake_whisperx,
    )
    monkeypatch.setattr(
        "app.providers.transcription.whisperx._verify_pyannote_model_access",
        lambda _token: None,
    )

    result = provider.check_ready(deep=True)

    assert result.status == "pass"
    assert fake_whisperx.load_model_calls == []


def test_whisperx_provider_model_load_readiness_loads_transcription_model(tmp_path):
    fake_whisperx = FakeWhisperXModule()
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=False,
        whisperx_module=fake_whisperx,
    )

    result = provider.check_ready(deep=True, load_models=True)

    assert result.status == "pass"
    assert len(fake_whisperx.load_model_calls) == 1


def test_whisperx_provider_readiness_rejects_missing_token(tmp_path):
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=True,
        hf_token="",
        whisperx_module=FakeWhisperXModule(),
    )

    result = provider.check_ready()

    assert result.status == "fail"
    assert "HF_TOKEN" in result.message


def test_whisperx_provider_uses_detected_language_for_alignment(tmp_path):
    fake_whisperx = FakeWhisperXModule(detected_language="es")
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=False,
        whisperx_module=fake_whisperx,
    )

    provider.transcribe(tmp_path / "audio.wav", "made up language")

    assert fake_whisperx.transcribe_calls[0]["language"] is None
    assert fake_whisperx.load_align_model_calls == [
        {
            "language_code": "es",
            "device": "cpu",
            "model_dir": str(tmp_path / "models"),
        }
    ]


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


def test_whisperx_provider_reports_missing_required_install(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "whisperx", None)
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=False,
    )

    with pytest.raises(WhisperXUnavailableError, match="requirements.txt"):
        provider.transcribe(tmp_path / "audio.wav", "English")


def test_whisperx_provider_raises_when_no_speech_segments(tmp_path):
    fake_whisperx = FakeWhisperXModule(
        aligned_segments=[
            {"start": 0.0, "end": 1.0, "text": "   "},
        ]
    )
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=False,
        whisperx_module=fake_whisperx,
    )

    with pytest.raises(ValueError, match="did not detect any speech"):
        provider.transcribe(tmp_path / "silent.wav", "English")
