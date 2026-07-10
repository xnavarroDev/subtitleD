import sys
from types import SimpleNamespace

import numpy as np
import pytest

from app.providers.transcription import (
    TranscriptSegment,
    TranscriptWord,
    WhisperXTranscriptionProvider,
    WhisperXUnavailableError,
    get_transcription_provider,
    normalize_language,
)
from app.providers.transcription.whisperx import (
    ExclusiveDiarizationPipeline,
    JapaneseAlignmentLoadError,
    _load_japanese_align_model,
    _verify_pyannote_model_access,
)
from app.utils.captions import flatten_transcript_words


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
                        {"word": "Hello", "start": 0.0, "end": 0.5, "score": 0.91, "speaker": "SPEAKER_00"},
                        {"word": "world", "start": 0.5, "end": 1.1, "score": 0.82, "speaker": "SPEAKER_00"},
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

    def __init__(self, model_name, token, device, cache_dir):
        self.model_name = model_name
        self.token = token
        self.device = device
        self.cache_dir = cache_dir
        self.calls = []
        self.instances.append(self)

    def __call__(self, audio, **kwargs):
        self.calls.append({"audio": audio, **kwargs})
        return "diarize-segments"


class FakeAnnotation:
    def __init__(self, intervals):
        self.intervals = intervals

    def itertracks(self, yield_label=False):
        assert yield_label is True
        return iter(self.intervals)


class FakePyannotePipeline:
    def __init__(self, output):
        self.output = output
        self.device = None
        self.calls = []

    def to(self, device):
        self.device = device
        return self

    def __call__(self, audio, **kwargs):
        self.calls.append({"audio": audio, **kwargs})
        return self.output


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
        ("pt-br", "pt"),
        ("zh-Hans", "zh"),
        ("zh-Hant", "zh"),
        ("zh-tw", "zh"),
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
        hf_cache_dir=tmp_path / "hf-cache",
        diarize=True,
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
            words=(
                TranscriptWord("Hello", 0.0, 0.5, "SPEAKER_00", 0.91),
                TranscriptWord("world", 0.5, 1.1, "SPEAKER_00", 0.82),
            ),
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
    assert diarization.model_name == "pyannote/speaker-diarization-community-1"
    assert diarization.token == "secret"
    assert diarization.device == "cpu"
    assert diarization.cache_dir == str(tmp_path / "hf-cache")
    assert diarization.calls == [
        {
            "audio": "audio-array",
            "min_speakers": 2,
            "max_speakers": 3,
        }
    ]
    assert fake_whisperx.assign_word_speakers_calls


def test_exclusive_pipeline_uses_transcript_friendly_timeline(tmp_path):
    segment_type = type("Segment", (), {})
    regular_segment = segment_type()
    regular_segment.start, regular_segment.end = 0.0, 2.0
    exclusive_segment = segment_type()
    exclusive_segment.start, exclusive_segment.end = 0.7, 1.1
    output = SimpleNamespace(
        speaker_diarization=FakeAnnotation(
            [(regular_segment, "regular-track", "SPEAKER_00")]
        ),
        exclusive_speaker_diarization=FakeAnnotation(
            [(exclusive_segment, "exclusive-track", "SPEAKER_01")]
        ),
    )
    fake_model = FakePyannotePipeline(output)
    factory_calls = []

    def pipeline_factory(model_name, **kwargs):
        factory_calls.append({"model_name": model_name, **kwargs})
        return fake_model

    pipeline = ExclusiveDiarizationPipeline(
        "pyannote/speaker-diarization-community-1",
        "secret",
        "cpu",
        str(tmp_path / "hf-cache"),
        pipeline_factory=pipeline_factory,
    )
    result = pipeline(
        np.zeros(16000, dtype=np.float32),
        min_speakers=2,
        max_speakers=2,
    )

    assert factory_calls == [{
        "model_name": "pyannote/speaker-diarization-community-1",
        "token": "secret",
        "cache_dir": str(tmp_path / "hf-cache"),
    }]
    assert str(fake_model.device) == "cpu"
    assert result[["start", "end", "speaker"]].to_dict("records") == [
        {"start": 0.7, "end": 1.1, "speaker": "SPEAKER_01"}
    ]
    assert fake_model.calls[0]["audio"]["waveform"].shape == (1, 16000)
    assert fake_model.calls[0]["audio"]["sample_rate"] == 16000
    assert fake_model.calls[0]["min_speakers"] == 2
    assert fake_model.calls[0]["max_speakers"] == 2


def test_exclusive_pipeline_fails_instead_of_silently_using_regular_output(tmp_path):
    output = SimpleNamespace(speaker_diarization=FakeAnnotation([]))
    fake_model = FakePyannotePipeline(output)
    pipeline = ExclusiveDiarizationPipeline(
        "pyannote/speaker-diarization-community-1",
        "secret",
        "cpu",
        str(tmp_path / "hf-cache"),
        pipeline_factory=lambda *_args, **_kwargs: fake_model,
    )

    with pytest.raises(RuntimeError, match="WHISPERX_DIARIZATION_OUTPUT=regular"):
        pipeline(np.zeros(16000, dtype=np.float32))


def test_provider_preserves_exclusive_output_recovery_message(tmp_path):
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models", diarize=True, hf_token="secret",
        whisperx_module=FakeWhisperXModule(),
    )

    def unavailable_exclusive_output(*_args, **_kwargs):
        raise RuntimeError(
            "Set WHISPERX_DIARIZATION_OUTPUT=regular to use the regular timeline."
        )

    provider._diarization_model = unavailable_exclusive_output

    with pytest.raises(RuntimeError, match="WHISPERX_DIARIZATION_OUTPUT=regular"):
        provider._assign_speakers(FakeWhisperXModule(), {"segments": []}, "audio")


def test_diarization_output_defaults_to_exclusive_and_accepts_regular(tmp_path):
    default_provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "default", diarize=False,
        whisperx_module=FakeWhisperXModule(),
    )
    regular_provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "regular", diarize=False,
        diarization_output="regular", whisperx_module=FakeWhisperXModule(),
    )

    assert default_provider.diarization_output == "exclusive"
    assert regular_provider.diarization_output == "regular"


def test_diarization_output_rejects_unknown_mode(tmp_path):
    with pytest.raises(ValueError, match="WHISPERX_DIARIZATION_OUTPUT"):
        WhisperXTranscriptionProvider(
            model_dir=tmp_path / "models", diarize=False,
            diarization_output="sometimes", whisperx_module=FakeWhisperXModule(),
        )


def test_provider_selects_exclusive_pipeline_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.providers.transcription.whisperx._verify_pyannote_model_access",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.providers.transcription.whisperx.ExclusiveDiarizationPipeline",
        FakeDiarizationPipeline,
    )
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models", diarize=True, hf_token="secret",
        whisperx_module=FakeWhisperXModule(),
    )

    assert isinstance(provider._get_diarization_model(), FakeDiarizationPipeline)


def test_provider_selects_regular_pipeline_as_escape_hatch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.providers.transcription.whisperx._verify_pyannote_model_access",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.providers.transcription.whisperx._load_diarization_pipeline_class",
        lambda: FakeDiarizationPipeline,
    )
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models", diarize=True, hf_token="secret",
        diarization_output="regular", whisperx_module=FakeWhisperXModule(),
    )

    assert isinstance(provider._get_diarization_model(), FakeDiarizationPipeline)


def test_whisperx_provider_quick_readiness_does_not_load_models(tmp_path):
    fake_whisperx = FakeWhisperXModule()
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=False,
        whisperx_module=fake_whisperx,
    )

    result = provider.check_ready(deep=False)

    assert result.status == "pass"
    assert result.details["diarization_output"] == "exclusive"
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
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.providers.transcription.whisperx._verify_japanese_alignment_revision",
        lambda *_args: None,
    )

    result = provider.check_ready(deep=True)

    assert result.status == "pass"
    assert fake_whisperx.load_model_calls == []


def test_whisperx_provider_model_load_readiness_loads_transcription_model(tmp_path, monkeypatch):
    fake_whisperx = FakeWhisperXModule()
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=False,
        whisperx_module=fake_whisperx,
    )
    monkeypatch.setattr(
        "app.providers.transcription.whisperx._verify_japanese_alignment_revision",
        lambda *_args: None,
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


def test_deep_readiness_warns_when_japanese_revision_is_unavailable_in_fallback_mode(
    tmp_path, monkeypatch
):
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models",
        diarize=False,
        whisperx_module=FakeWhisperXModule(),
    )
    monkeypatch.setattr(
        "app.providers.transcription.whisperx._verify_japanese_alignment_revision",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("revision unavailable")),
    )

    result = provider.check_ready(deep=True)

    assert result.status == "warn"
    assert result.ready is True
    assert "Japanese alignment revision" in result.message


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


def test_whisperx_provider_passes_glossary_as_recognition_hints(tmp_path):
    fake_whisperx = FakeWhisperXModule()
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models", diarize=False, whisperx_module=fake_whisperx,
    )

    provider.transcribe(tmp_path / "audio.wav", "English", glossary="Alonzo, SubtitleD")

    assert fake_whisperx.load_model_calls[0]["asr_options"] == {
        "initial_prompt": "Alonzo, SubtitleD", "hotwords": "Alonzo, SubtitleD"
    }


def test_whisper_model_cache_evicts_previous_glossary(tmp_path):
    fake_whisperx = FakeWhisperXModule()
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models", diarize=False, whisperx_module=fake_whisperx,
    )

    provider.transcribe(tmp_path / "one.wav", "English", glossary="Alonzo")
    provider.transcribe(tmp_path / "two.wav", "English", glossary="SubtitleD")

    assert len(fake_whisperx.load_model_calls) == 2
    assert len(WhisperXTranscriptionProvider._model_cache) == 1


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


def test_pyannote_access_check_uses_community_model_and_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "huggingface_hub.hf_hub_download",
        lambda **kwargs: calls.append(kwargs),
    )

    _verify_pyannote_model_access("secret", cache_dir=tmp_path / "hf-cache")

    assert calls == [
        {
            "repo_id": "pyannote/speaker-diarization-community-1",
            "filename": "config.yaml",
            "token": "secret",
            "cache_dir": str(tmp_path / "hf-cache"),
        }
    ]


def test_pyannote_access_check_reports_community_terms(monkeypatch):
    monkeypatch.setattr(
        "huggingface_hub.hf_hub_download",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("forbidden")),
    )

    with pytest.raises(RuntimeError, match="speaker-diarization-community-1"):
        _verify_pyannote_model_access("secret")


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


def test_japanese_uses_pinned_custom_safetensors_loader(tmp_path):
    fake_whisperx = FakeWhisperXModule(detected_language="ja")
    calls = []

    def loader(**kwargs):
        calls.append(kwargs)
        return "ja-align-model", {"language": "ja", "dictionary": {"あ": 1}, "type": "huggingface"}

    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models", diarize=False,
        whisperx_module=fake_whisperx, japanese_align_loader=loader,
    )

    segments = provider.transcribe(tmp_path / "audio.wav", "Japanese")

    assert calls[0]["model_name"] == "jonatasgrosman/wav2vec2-large-xlsr-53-japanese"
    assert calls[0]["revision"] == "2785e99ab97df77a32b5bd0ece5c9fa188a02f19"
    assert calls[0]["require_safetensors"] is True
    assert all(segment.timing_quality == "forced_aligned" for segment in segments)


def test_japanese_model_load_failure_uses_estimated_word_timing(tmp_path):
    fake_whisperx = FakeWhisperXModule(
        detected_language="ja",
        transcribed_segments=[{"start": 0.0, "end": 1.0, "text": "日本 語"}],
    )

    def broken_loader(**kwargs):
        raise JapaneseAlignmentLoadError("model unavailable")

    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models", diarize=False,
        whisperx_module=fake_whisperx, japanese_align_loader=broken_loader,
    )

    segments = provider.transcribe(tmp_path / "audio.wav", "Japanese")
    words = flatten_transcript_words(segments)

    assert segments[0].timing_quality == "estimated"
    assert [word.timing_quality for word in words] == ["estimated", "estimated"]
    assert words[0].start_time == 0 and words[-1].end_time == 1
    assert provider.last_warnings == [
        "Japanese forced alignment was unavailable. Estimated word timing was used."
    ]


def test_japanese_model_load_failure_can_remain_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv("WHISPERX_ALIGNMENT_FAILURE_MODE", "fail")

    def broken_loader(**kwargs):
        raise JapaneseAlignmentLoadError("model unavailable")

    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models", diarize=False,
        whisperx_module=FakeWhisperXModule(detected_language="ja"),
        japanese_align_loader=broken_loader,
    )

    with pytest.raises(JapaneseAlignmentLoadError):
        provider.transcribe(tmp_path / "audio.wav", "Japanese")


def test_japanese_alignment_execution_errors_are_not_hidden(tmp_path):
    fake_whisperx = FakeWhisperXModule(detected_language="ja")
    fake_whisperx.align = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("alignment bug"))
    provider = WhisperXTranscriptionProvider(
        model_dir=tmp_path / "models", diarize=False,
        whisperx_module=fake_whisperx,
        japanese_align_loader=lambda **kwargs: ("model", {"language": "ja"}),
    )

    with pytest.raises(RuntimeError, match="alignment bug"):
        provider.transcribe(tmp_path / "audio.wav", "Japanese")


def test_japanese_loader_pins_revision_and_requires_safetensors(tmp_path, monkeypatch):
    import transformers

    calls = {}

    class Processor:
        tokenizer = type("Tokenizer", (), {"get_vocab": lambda self: {"あ": 1}})()

    class Model:
        def to(self, device):
            calls["device"] = device
            return self

    monkeypatch.setattr(transformers.Wav2Vec2Processor, "from_pretrained", lambda *args, **kwargs: calls.setdefault("processor", (args, kwargs)) and Processor())
    monkeypatch.setattr(transformers.Wav2Vec2ForCTC, "from_pretrained", lambda *args, **kwargs: calls.setdefault("model", (args, kwargs)) and Model())

    _model, metadata = _load_japanese_align_model("repo/model", "fixed-sha", "cpu", str(tmp_path), True)

    assert calls["processor"][1]["revision"] == "fixed-sha"
    assert calls["processor"][1]["trust_remote_code"] is False
    assert calls["model"][1]["revision"] == "fixed-sha"
    assert calls["model"][1]["use_safetensors"] is True
    assert calls["model"][1]["trust_remote_code"] is False
    assert metadata["type"] == "huggingface"
