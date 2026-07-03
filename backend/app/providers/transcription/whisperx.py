import gc
import importlib.metadata
import tempfile
from pathlib import Path

from ...diagnostics import DiagnosticCheck, FAIL, PASS, WARN
from .base import (
    BaseTranscriptionProvider,
    TranscriptSegment,
    TranscriptWord,
    coerce_bool,
    get_setting,
    normalize_language,
)


_UNSET = object()


class WhisperXUnavailableError(RuntimeError):
    """Raised when optional WhisperX dependencies are not installed."""


class JapaneseAlignmentLoadError(RuntimeError):
    """Raised only when the pinned Japanese forced-alignment model cannot load."""


class WhisperXTranscriptionProvider(BaseTranscriptionProvider):
    """WhisperX provider with forced alignment and optional diarization."""

    _model_cache = {}
    _align_model_cache = {}

    def __init__(
        self,
        model_size=None,
        device=None,
        compute_type=None,
        batch_size=None,
        model_dir=None,
        diarize=None,
        hf_token=None,
        whisperx_module=_UNSET,
        diarization_pipeline_class=None,
        japanese_align_loader=None,
    ):
        self.model_size = model_size or get_setting("WHISPER_MODEL_SIZE", "base")
        self.device = device or get_setting("WHISPER_DEVICE", "cpu")
        self.compute_type = compute_type or get_setting("WHISPER_COMPUTE_TYPE", "int8")
        self.batch_size = int(
            batch_size
            if batch_size is not None
            else get_setting("WHISPERX_BATCH_SIZE", 16)
        )
        self.model_dir = Path(
            model_dir or get_setting("WHISPER_MODEL_DIR", Path("storage") / "models")
        )
        self.diarize = coerce_bool(
            diarize if diarize is not None else get_setting("WHISPERX_DIARIZE", True)
        )
        token = hf_token if hf_token is not None else get_setting("HF_TOKEN", "")
        self.hf_token = str(token).strip()
        self.whisperx_module = whisperx_module
        self.diarization_pipeline_class = diarization_pipeline_class
        self.japanese_align_loader = japanese_align_loader or _load_japanese_align_model
        self.ja_align_model = str(get_setting(
            "WHISPERX_JA_ALIGN_MODEL", "jonatasgrosman/wav2vec2-large-xlsr-53-japanese"
        )).strip()
        self.ja_align_revision = str(get_setting(
            "WHISPERX_JA_ALIGN_REVISION", "2785e99ab97df77a32b5bd0ece5c9fa188a02f19"
        )).strip()
        self.ja_require_safetensors = coerce_bool(
            get_setting("WHISPERX_JA_REQUIRE_SAFETENSORS", True)
        )
        self.alignment_failure_mode = str(
            get_setting("WHISPERX_ALIGNMENT_FAILURE_MODE", "fallback")
        ).strip().lower()
        if self.alignment_failure_mode not in {"fail", "fallback"}:
            raise ValueError("WHISPERX_ALIGNMENT_FAILURE_MODE must be 'fail' or 'fallback'.")
        self.last_warnings = []
        self.last_detected_language = None
        self._diarization_model = None

    def check_ready(self, deep=False, load_models=False, diarize=None):
        """Validate WhisperX configuration and optionally load provider models."""
        use_diarization = self.diarize if diarize is None else coerce_bool(diarize)
        try:
            whisperx = self._get_whisperx_module()
            import matplotlib.pyplot  # noqa: F401
            import pyannote.audio  # noqa: F401
            import torch
            import torchaudio
        except Exception as exc:
            return DiagnosticCheck(
                "transcription",
                FAIL,
                f"WhisperX dependency import failed: {exc}",
            )

        if not hasattr(torchaudio, "AudioMetaData"):
            return DiagnosticCheck(
                "transcription",
                FAIL,
                "Installed TorchAudio is incompatible with pyannote.audio.",
            )
        if self.device.startswith("cuda") and not torch.cuda.is_available():
            return DiagnosticCheck(
                "transcription",
                FAIL,
                f"WhisperX is configured for {self.device}, but CUDA is unavailable.",
            )
        if use_diarization and not self.hf_token:
            return DiagnosticCheck(
                "transcription",
                FAIL,
                "WhisperX diarization requires HF_TOKEN.",
            )

        try:
            self.model_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.model_dir):
                pass
        except OSError:
            return DiagnosticCheck(
                "transcription",
                FAIL,
                "WhisperX model directory is not writable.",
            )

        if deep and use_diarization:
            try:
                _patch_hf_hub_use_auth_token_alias()
                _verify_pyannote_model_access(self.hf_token)
            except Exception as exc:
                return DiagnosticCheck(
                    "transcription",
                    FAIL,
                    f"WhisperX deep readiness check failed: {exc}",
                )

        japanese_remote_check = None
        if deep:
            try:
                _verify_japanese_alignment_revision(
                    self.ja_align_model,
                    self.ja_align_revision,
                    self.ja_require_safetensors,
                )
                japanese_remote_check = "available"
            except Exception as exc:
                status = WARN if self.alignment_failure_mode == "fallback" else FAIL
                return DiagnosticCheck(
                    "transcription",
                    status,
                    f"Japanese alignment revision check failed: {exc}",
                    {"japanese_alignment_fallback": self.alignment_failure_mode == "fallback"},
                )

        if load_models:
            try:
                self._get_model(whisperx, None)
                if use_diarization:
                    self._get_diarization_model()
            except Exception as exc:
                return DiagnosticCheck(
                    "transcription",
                    FAIL,
                    f"WhisperX model-load check failed: {exc}",
                )

        versions = {}
        for package in ("whisperx", "torch", "torchaudio", "pyannote.audio"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = "unknown"
        if load_models:
            message = "WhisperX models and diarization loaded successfully."
        elif deep and use_diarization:
            message = "WhisperX dependencies and gated model access are ready."
        else:
            message = "WhisperX configuration and dependencies are ready."
        return DiagnosticCheck(
            "transcription",
            PASS,
            message,
            {
                "device": self.device,
                "model_size": self.model_size,
                "diarization": use_diarization,
                "versions": versions,
                "japanese_alignment": {
                    "model": self.ja_align_model,
                    "revision": self.ja_align_revision,
                    "safetensors_required": self.ja_require_safetensors,
                    "fallback_mode": self.alignment_failure_mode,
                    "remote_check": japanese_remote_check,
                    "cached": _japanese_alignment_is_cached(
                        self.model_dir, self.ja_align_model, self.ja_align_revision
                    ),
                },
            },
        )

    def transcribe(self, audio_path, source_language, min_speakers=None, max_speakers=None, glossary=None, diarize=None):
        """Transcribe, align, and optionally diarize an audio file."""
        self.last_warnings = []
        use_diarization = self.diarize if diarize is None else coerce_bool(diarize)
        if use_diarization and not self.hf_token:
            raise RuntimeError(
                "WhisperX diarization requires HF_TOKEN. Set HF_TOKEN to a Hugging Face "
                "token with access to the pyannote speaker diarization model, or set "
                "WHISPERX_DIARIZE=false."
            )

        whisperx = self._get_whisperx_module()
        self.model_dir.mkdir(parents=True, exist_ok=True)

        language = normalize_language(source_language)
        audio = whisperx.load_audio(str(audio_path))
        model = self._get_model(whisperx, language, glossary)
        result = model.transcribe(
            audio,
            batch_size=self.batch_size,
            language=language,
            task="transcribe",
        )

        segments = result.get("segments") or []
        alignment_language = language or result.get("language")
        if not alignment_language:
            raise ValueError("WhisperX did not detect a language for alignment.")
        self.last_detected_language = alignment_language

        timing_quality = "forced_aligned"
        try:
            align_model, metadata = self._get_align_model(whisperx, alignment_language)
        except JapaneseAlignmentLoadError:
            if alignment_language != "ja" or self.alignment_failure_mode != "fallback":
                raise
            timing_quality = "estimated"
            self.last_warnings.append(
                "Japanese forced alignment was unavailable. Estimated word timing was used."
            )
            result = {**result, "segments": segments}
        else:
            result = whisperx.align(
                segments,
                align_model,
                metadata,
                audio,
                self.device,
                return_char_alignments=False,
            )

        if use_diarization:
            result = self._assign_speakers(
                whisperx,
                result,
                audio,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )

        transcript_segments = self._to_transcript_segments(result, timing_quality)
        if not transcript_segments:
            raise ValueError("WhisperX did not detect any speech segments in the audio.")
        return transcript_segments

    def _get_whisperx_module(self):
        if self.whisperx_module is not _UNSET:
            return self.whisperx_module
        return _load_whisperx_module()

    def _get_model(self, whisperx, language, glossary=None):
        glossary = str(glossary or "").strip()
        cache_key = (
            whisperx,
            self.model_size,
            self.device,
            self.compute_type,
            str(self.model_dir),
            language,
            glossary,
        )
        if cache_key not in self._model_cache:
            cache_size = max(int(get_setting("WHISPER_MODEL_CACHE_SIZE", 1)), 1)
            while len(self._model_cache) >= cache_size:
                oldest_key = next(iter(self._model_cache))
                evicted = self._model_cache.pop(oldest_key)
                del evicted
                gc.collect()
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass
            kwargs = {
                "compute_type": self.compute_type,
                "download_root": str(self.model_dir),
                "language": language,
            }
            if glossary:
                kwargs["asr_options"] = {"initial_prompt": glossary, "hotwords": glossary}
            self._model_cache[cache_key] = whisperx.load_model(
                self.model_size,
                self.device,
                **kwargs,
            )
        return self._model_cache[cache_key]

    def _get_align_model(self, whisperx, language):
        japanese_key = (
            self.ja_align_model, self.ja_align_revision, self.ja_require_safetensors
        ) if language == "ja" else None
        cache_key = (whisperx, language, self.device, str(self.model_dir), japanese_key)
        if cache_key not in self._align_model_cache:
            if language == "ja":
                try:
                    self._align_model_cache[cache_key] = self.japanese_align_loader(
                        model_name=self.ja_align_model,
                        revision=self.ja_align_revision,
                        device=self.device,
                        model_dir=str(self.model_dir),
                        require_safetensors=self.ja_require_safetensors,
                    )
                except JapaneseAlignmentLoadError:
                    raise
                except Exception as exc:
                    raise JapaneseAlignmentLoadError(
                        f"Could not load pinned Japanese alignment model: {exc}"
                    ) from exc
            else:
                self._align_model_cache[cache_key] = whisperx.load_align_model(
                    language_code=language,
                    device=self.device,
                    model_dir=str(self.model_dir),
                )
        return self._align_model_cache[cache_key]

    def _assign_speakers(self, whisperx, result, audio, min_speakers=None, max_speakers=None):
        diarization_model = self._get_diarization_model()
        diarization_kwargs = {}
        if min_speakers is not None:
            diarization_kwargs["min_speakers"] = int(min_speakers)
        if max_speakers is not None:
            diarization_kwargs["max_speakers"] = int(max_speakers)

        try:
            diarize_segments = diarization_model(audio, **diarization_kwargs)
            return whisperx.assign_word_speakers(diarize_segments, result)
        except Exception as exc:
            raise RuntimeError(
                "WhisperX diarization failed. Confirm HF_TOKEN has access to the "
                "pyannote speaker diarization model and try again."
            ) from exc

    def _get_diarization_model(self):
        if self._diarization_model is None:
            use_real_pipeline = self.diarization_pipeline_class is None
            pipeline_class = (
                self.diarization_pipeline_class or _load_diarization_pipeline_class()
            )
            _patch_hf_hub_use_auth_token_alias()
            if use_real_pipeline:
                _verify_pyannote_model_access(self.hf_token)

            try:
                self._diarization_model = pipeline_class(
                    use_auth_token=self.hf_token,
                    device=self.device,
                )
            except Exception as exc:
                raise RuntimeError(
                    "WhisperX diarization failed to load. Confirm HF_TOKEN has access "
                    "to the pyannote speaker diarization model and try again."
                ) from exc
        return self._diarization_model

    def _to_transcript_segments(self, result, timing_quality="forced_aligned"):
        transcript_segments = []
        for segment in result.get("segments") or []:
            text = (segment.get("text") or "").strip()
            if not text:
                continue

            transcript_segments.append(
                TranscriptSegment(
                    start_time=float(segment["start"]),
                    end_time=float(segment["end"]),
                    text=text,
                    speaker_label=_segment_speaker(segment),
                    words=tuple(
                        word for word in (
                            _to_transcript_word(value, timing_quality)
                            for value in segment.get("words") or []
                        ) if word is not None
                    ),
                    timing_quality=timing_quality,
                )
            )

        return sorted(transcript_segments, key=lambda segment: segment.start_time)


def _to_transcript_word(value, timing_quality="forced_aligned"):
    text = (value.get("word") or "").strip()
    if not text:
        return None
    return TranscriptWord(
        text=text,
        start_time=_optional_float(value.get("start")),
        end_time=_optional_float(value.get("end")),
        speaker_label=(value.get("speaker") or "").strip() or None,
        confidence=_optional_float(value.get("score")),
        timing_quality=timing_quality,
    )


def _load_japanese_align_model(model_name, revision, device, model_dir, require_safetensors=True):
    """Load a revision-pinned Japanese CTC model in WhisperX metadata format."""
    try:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        processor = Wav2Vec2Processor.from_pretrained(
            model_name, revision=revision, cache_dir=model_dir,
            trust_remote_code=False,
        )
        model = Wav2Vec2ForCTC.from_pretrained(
            model_name, revision=revision, cache_dir=model_dir,
            use_safetensors=bool(require_safetensors), trust_remote_code=False,
        ).to(device)
        dictionary = {
            token.lower(): code for token, code in processor.tokenizer.get_vocab().items()
        }
        return model, {"language": "ja", "dictionary": dictionary, "type": "huggingface"}
    except Exception as exc:
        raise JapaneseAlignmentLoadError(
            f'Japanese alignment model "{model_name}" at revision "{revision}" could not load safely.'
        ) from exc


def _verify_japanese_alignment_revision(model_name, revision, require_safetensors=True):
    from huggingface_hub import HfApi

    info = HfApi().model_info(model_name, revision=revision, files_metadata=False)
    files = {item.rfilename for item in (info.siblings or [])}
    if require_safetensors and "model.safetensors" not in files:
        raise RuntimeError("Pinned revision does not contain model.safetensors.")


def _japanese_alignment_is_cached(model_dir, model_name, revision):
    repo_folder = "models--" + model_name.replace("/", "--")
    snapshot = Path(model_dir) / repo_folder / "snapshots" / revision
    return (snapshot / "model.safetensors").exists()


def _optional_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _segment_speaker(segment):
    speaker = (segment.get("speaker") or "").strip()
    if speaker:
        return speaker

    speaker_counts = {}
    for word in segment.get("words") or []:
        speaker = (word.get("speaker") or "").strip()
        if speaker:
            speaker_counts[speaker] = speaker_counts.get(speaker, 0) + 1
    if not speaker_counts:
        return None
    return max(speaker_counts.items(), key=lambda item: item[1])[0]


def _load_whisperx_module():
    try:
        import whisperx
    except ImportError as exc:
        raise WhisperXUnavailableError(
            "WhisperX is not installed. Install backend/requirements.txt "
            "or rebuild the backend image."
        ) from exc
    return whisperx


def _load_diarization_pipeline_class():
    try:
        from whisperx.diarize import DiarizationPipeline
    except ImportError as exc:
        raise WhisperXUnavailableError(
            "WhisperX diarization dependencies are not installed. Install "
            "backend/requirements.txt or rebuild the backend image."
        ) from exc
    return DiarizationPipeline


def _patch_hf_hub_use_auth_token_alias():
    """Support pyannote 3.x calls against newer huggingface-hub releases."""
    try:
        import huggingface_hub
        import pyannote.audio.core.model as pyannote_model
        import pyannote.audio.core.pipeline as pyannote_pipeline
    except ImportError:
        return

    current_download = huggingface_hub.hf_hub_download
    if getattr(current_download, "_subtitled_accepts_use_auth_token", False):
        patched_download = current_download
    else:

        def patched_download(*args, **kwargs):
            if "use_auth_token" in kwargs and "token" not in kwargs:
                kwargs["token"] = kwargs.pop("use_auth_token")
            else:
                kwargs.pop("use_auth_token", None)
            return current_download(*args, **kwargs)

        patched_download._subtitled_accepts_use_auth_token = True

    huggingface_hub.hf_hub_download = patched_download
    pyannote_model.hf_hub_download = patched_download
    pyannote_pipeline.hf_hub_download = patched_download


def _verify_pyannote_model_access(token):
    """Fail early with actionable gated-model instructions."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return

    required_files = [
        ("pyannote/speaker-diarization-3.1", "config.yaml"),
        ("pyannote/segmentation-3.0", "pytorch_model.bin"),
    ]
    for repo_id, filename in required_files:
        try:
            hf_hub_download(repo_id=repo_id, filename=filename, token=token)
        except Exception as exc:
            raise RuntimeError(
                "HF_TOKEN cannot download required pyannote diarization files. "
                "Accept the user conditions for both "
                "https://huggingface.co/pyannote/speaker-diarization-3.1 and "
                "https://huggingface.co/pyannote/segmentation-3.0, then restart "
                "the worker and retry."
            ) from exc
