"""Local multilingual machine translation powered by NLLB and CTranslate2."""

import json
import threading
import re
from dataclasses import dataclass
from pathlib import Path

from flask import current_app, has_app_context

from ..diagnostics import DiagnosticCheck, FAIL, PASS, WARN
from .translation_languages import language_catalog, nllb_language_code


MODEL_METADATA_FILENAME = "subtitleD-model.json"


@dataclass(frozen=True)
class TranslationOutput:
    text: str
    provider: str
    model: str | None = None
    warning: str | None = None


class LocalNllbTranslationProvider:
    _translator_cache = {}
    _tokenizer_cache = {}
    _runtime_lock = threading.Lock()

    def __init__(
        self,
        model_dir=None,
        tokenizer_dir=None,
        model_name=None,
        model_revision=None,
        device=None,
        compute_type=None,
        batch_size=None,
        beam_size=None,
        max_input_tokens=None,
        translator_class=None,
        tokenizer_class=None,
    ):
        root = Path(_setting("LOCAL_MT_MODEL_DIR", "/app/storage/models/nllb-200-distilled-600M-ct2"))
        self.model_dir = Path(model_dir or root)
        self.tokenizer_dir = Path(tokenizer_dir or _setting(
            "LOCAL_MT_TOKENIZER_DIR", root.parent / "nllb-200-distilled-600M-tokenizer"
        ))
        self.model_name = str(model_name or _setting("LOCAL_MT_MODEL", "facebook/nllb-200-distilled-600M"))
        self.model_revision = str(model_revision or _setting(
            "LOCAL_MT_MODEL_REVISION", "b3bbac6cd67efa90e0fcbe4c882ec79cfd782a17"
        ))
        self.device = str(device or _setting("LOCAL_MT_DEVICE", "cpu"))
        self.compute_type = str(compute_type or _setting("LOCAL_MT_COMPUTE_TYPE", "int8"))
        self.batch_size = int(batch_size or _setting("LOCAL_MT_BATCH_SIZE", 4))
        self.beam_size = int(beam_size or _setting("LOCAL_MT_BEAM_SIZE", 4))
        self.max_input_tokens = int(max_input_tokens or _setting("LOCAL_MT_MAX_INPUT_TOKENS", 512))
        self.translator_class = translator_class
        self.tokenizer_class = tokenizer_class

    @property
    def provider_name(self):
        return "nllb-ct2"

    @property
    def model_identity(self):
        return f"{self.model_name}@{self.model_revision}"

    def get_languages(self):
        return language_catalog()

    def check_ready(self, source_language=None, target_language=None):
        try:
            if source_language and str(source_language).casefold() != "auto":
                nllb_language_code(source_language)
            if target_language:
                nllb_language_code(target_language)
        except ValueError as exc:
            return DiagnosticCheck("translation", FAIL, str(exc))
        missing = []
        if not (self.model_dir / "model.bin").is_file():
            missing.append(str(self.model_dir / "model.bin"))
        if not (self.tokenizer_dir / "tokenizer_config.json").is_file():
            missing.append(str(self.tokenizer_dir / "tokenizer_config.json"))
        metadata_path = self.model_dir / MODEL_METADATA_FILENAME
        if not metadata_path.is_file():
            missing.append(str(metadata_path))
        if missing:
            return DiagnosticCheck(
                "translation",
                FAIL,
                "Local NLLB model is not installed. Run `flask --app run setup-local-translation`.",
                {"provider": self.provider_name, "missing": missing},
            )
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return DiagnosticCheck(
                "translation", FAIL,
                "Local NLLB model provenance metadata is invalid; rerun setup-local-translation.",
                {"provider": self.provider_name, "error": str(exc)},
            )
        if (
            metadata.get("model") != self.model_name
            or metadata.get("revision") != self.model_revision
        ):
            return DiagnosticCheck(
                "translation", FAIL,
                "Installed NLLB model does not match the configured pinned revision.",
                {"provider": self.provider_name, "installed": metadata},
            )
        return DiagnosticCheck(
            "translation",
            PASS,
            "Local NLLB translation model is ready.",
            {
                "provider": self.provider_name,
                "model": self.model_name,
                "revision": self.model_revision,
                "device": self.device,
                "compute_type": self.compute_type,
            },
        )

    def translate(self, text, source_language, target_language):
        return self.translate_with_metadata(text, source_language, target_language).text

    def translate_with_metadata(self, text, source_language, target_language):
        return self.translate_batch_with_metadata(
            [text], source_language, target_language
        )[0]

    def translate_batch_with_metadata(self, texts, source_language, target_language):
        if not texts:
            return []
        source_code = nllb_language_code(source_language)
        target_code = nllb_language_code(target_language)
        translator, tokenizer = self._runtime(source_code)
        sources = []
        for text in texts:
            encoded = tokenizer.encode(str(text), truncation=True, max_length=self.max_input_tokens)
            sources.append(tokenizer.convert_ids_to_tokens(encoded))
        results = []
        batch_size = max(self.batch_size, 1)
        for offset in range(0, len(sources), batch_size):
            batch = sources[offset:offset + batch_size]
            results.extend(translator.translate_batch(
                batch,
                target_prefix=[[target_code] for _ in batch],
                beam_size=self.beam_size,
                max_decoding_length=self.max_input_tokens,
            ))
        outputs = []
        for result in results:
            tokens = result.hypotheses[0]
            if tokens and tokens[0] == target_code:
                tokens = tokens[1:]
            token_ids = tokenizer.convert_tokens_to_ids(tokens)
            text = tokenizer.decode(token_ids, skip_special_tokens=True).strip()
            if not text:
                raise RuntimeError("Local NLLB returned empty translation text.")
            outputs.append(TranslationOutput(text, self.provider_name, self.model_identity))
        return outputs

    def _runtime(self, source_code):
        translator_key = (
            str(self.model_dir), self.device, self.compute_type,
            self.translator_class,
        )
        tokenizer_key = (
            str(self.tokenizer_dir), source_code, self.tokenizer_class,
        )
        with self._runtime_lock:
            if translator_key not in self._translator_cache:
                if self.check_ready().status == FAIL:
                    raise RuntimeError(
                        "Local NLLB model is not installed. Run `flask --app run setup-local-translation`."
                    )
                translator_class = self.translator_class
                if translator_class is None:
                    import ctranslate2
                    translator_class = ctranslate2.Translator
                self._translator_cache[translator_key] = translator_class(
                    str(self.model_dir),
                    device=self.device,
                    compute_type=self.compute_type,
                )
            if tokenizer_key not in self._tokenizer_cache:
                cache_size = max(int(_setting("LOCAL_MT_TOKENIZER_CACHE_SIZE", 8)), 1)
                while len(self._tokenizer_cache) >= cache_size:
                    self._tokenizer_cache.pop(next(iter(self._tokenizer_cache)))
                tokenizer_class = self.tokenizer_class
                if tokenizer_class is None:
                    from transformers import AutoTokenizer
                    tokenizer_class = AutoTokenizer
                self._tokenizer_cache[tokenizer_key] = tokenizer_class.from_pretrained(
                    str(self.tokenizer_dir),
                    src_lang=source_code,
                    local_files_only=True,
                )
            return (
                self._translator_cache[translator_key],
                self._tokenizer_cache[tokenizer_key],
            )


class FallbackTranslationProvider:
    """Use a local primary translator and preserve a configured local fallback."""

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback
        self._primary_unavailable_reason = None

    @property
    def provider_name(self):
        return getattr(self.primary, "provider_name", "local")

    def get_languages(self):
        return self.primary.get_languages()

    def check_ready(self, source_language=None, target_language=None):
        primary = self.primary.check_ready(source_language, target_language)
        if primary.status != FAIL:
            return primary
        fallback = self.fallback.check_ready(source_language, target_language)
        if fallback.status != FAIL:
            self._primary_unavailable_reason = primary.message
            return DiagnosticCheck(
                "translation",
                WARN,
                f"{primary.message} {fallback.message}",
                {"primary": primary.details, "fallback": fallback.details},
            )
        return DiagnosticCheck(
            "translation", FAIL,
            f"{primary.message} Fallback unavailable: {fallback.message}",
            {"primary": primary.details, "fallback": fallback.details},
        )

    def translate(self, text, source_language, target_language):
        return self.translate_with_metadata(text, source_language, target_language).text

    def translate_with_metadata(self, text, source_language, target_language):
        return self.translate_with_context(text, source_language, target_language, (), ())

    def translate_with_context(
        self, text, source_language, target_language,
        context_before=(), context_after=(),
    ):
        try:
            if self._primary_unavailable_reason:
                raise RuntimeError(self._primary_unavailable_reason)
            if hasattr(self.primary, "translate_with_context"):
                output = self.primary.translate_with_context(
                    text, source_language, target_language,
                    context_before, context_after,
                )
            else:
                output = self.primary.translate_with_metadata(
                    text, source_language, target_language
                )
            issue = translation_quality_issue(output.text, text)
            if issue:
                raise RuntimeError(issue)
            return output
        except Exception as exc:
            if hasattr(self.fallback, "translate_with_context"):
                fallback_output = self.fallback.translate_with_context(
                    text, source_language, target_language,
                    context_before, context_after,
                )
            elif hasattr(self.fallback, "translate_with_metadata"):
                fallback_output = self.fallback.translate_with_metadata(
                    text, source_language, target_language
                )
            else:
                fallback_output = TranslationOutput(
                    self.fallback.translate(text, source_language, target_language),
                    getattr(self.fallback, "provider_name", "fallback"),
                )
            primary_name = getattr(self.primary, "provider_name", "Primary translator")
            warning = (
                f"{primary_name} translation failed; {fallback_output.provider} "
                f"fallback was used: {exc}"
            )
            if fallback_output.warning:
                warning = f"{warning} {fallback_output.warning}"
            return TranslationOutput(
                fallback_output.text,
                fallback_output.provider,
                fallback_output.model,
                warning=warning,
            )


def translation_quality_issue(translated_text, source_text):
    """Reject obvious local-MT degeneration without judging normal wording."""
    translated = str(translated_text or "").strip()
    if not translated:
        return "primary translator returned empty text"
    tokens = re.findall(r"\w+", translated.casefold(), flags=re.UNICODE)
    if len(tokens) >= 6:
        counts = {token: tokens.count(token) for token in set(tokens)}
        repeated = max(counts.values(), default=0)
        unique_ratio = len(counts) / len(tokens)
        if repeated >= 4 and (repeated / len(tokens) >= 0.45 or unique_ratio <= 0.25):
            return "primary translator produced degenerate repetition"
    compact_output = re.sub(r"\W+", "", translated.casefold(), flags=re.UNICODE)
    compact_source = re.sub(r"\W+", "", str(source_text).casefold(), flags=re.UNICODE)
    if compact_output and compact_output == compact_source and len(compact_output) > 8:
        return "primary translator returned untranslated source text"
    return None


def _setting(name, default):
    if has_app_context() and name in current_app.config:
        return current_app.config[name]
    import os
    return os.getenv(name, default)
