import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app, has_app_context

from ..diagnostics import DiagnosticCheck, FAIL, PASS


_LANGUAGE_CODES = {
    "arabic": "ar",
    "ar": "ar",
    "chinese": "zh",
    "zh": "zh",
    "dutch": "nl",
    "nl": "nl",
    "english": "en",
    "en": "en",
    "french": "fr",
    "fr": "fr",
    "german": "de",
    "de": "de",
    "hindi": "hi",
    "hi": "hi",
    "italian": "it",
    "it": "it",
    "japanese": "ja",
    "ja": "ja",
    "korean": "ko",
    "ko": "ko",
    "portuguese": "pt",
    "pt": "pt",
    "russian": "ru",
    "ru": "ru",
    "spanish": "es",
    "es": "es",
}


class BaseTranslationProvider:
    """Interface for text translation implementations."""

    def check_ready(self, source_language=None, target_language=None):
        """Return a provider-specific diagnostic readiness result."""
        raise NotImplementedError

    def translate(self, text, source_language, target_language):
        """Translate one subtitle segment while preserving segment timing."""
        raise NotImplementedError


class MockTranslationProvider(BaseTranslationProvider):
    """Small visible mock translator for local development and demos."""

    _dictionaries = {
        "spanish": {
            "Welcome to this product walkthrough.": "Bienvenido a este recorrido del producto.",
            "We will turn a video into editable subtitles.": "Convertiremos un video en subtitulos editables.",
            "After translation, you can review every line.": "Despues de la traduccion, puedes revisar cada linea.",
            "Finally, SubtitleD renders a new subtitled video.": "Finalmente, SubtitleD genera un nuevo video subtitulado.",
        },
        "es": {
            "Welcome to this product walkthrough.": "Bienvenido a este recorrido del producto.",
            "We will turn a video into editable subtitles.": "Convertiremos un video en subtitulos editables.",
            "After translation, you can review every line.": "Despues de la traduccion, puedes revisar cada linea.",
            "Finally, SubtitleD renders a new subtitled video.": "Finalmente, SubtitleD genera un nuevo video subtitulado.",
        },
        "french": {
            "Welcome to this product walkthrough.": "Bienvenue dans cette presentation du produit.",
            "We will turn a video into editable subtitles.": "Nous allons transformer une video en sous-titres modifiables.",
            "After translation, you can review every line.": "Apres traduction, vous pouvez relire chaque ligne.",
            "Finally, SubtitleD renders a new subtitled video.": "Enfin, SubtitleD genere une nouvelle video sous-titree.",
        },
        "fr": {
            "Welcome to this product walkthrough.": "Bienvenue dans cette presentation du produit.",
            "We will turn a video into editable subtitles.": "Nous allons transformer une video en sous-titres modifiables.",
            "After translation, you can review every line.": "Apres traduction, vous pouvez relire chaque ligne.",
            "Finally, SubtitleD renders a new subtitled video.": "Enfin, SubtitleD genere une nouvelle video sous-titree.",
        },
    }

    def check_ready(self, source_language=None, target_language=None):
        return DiagnosticCheck(
            "translation",
            PASS,
            "Mock translation provider is ready.",
            {"provider": "mock"},
        )

    def translate(self, text, source_language, target_language):
        # Provider boundary: real translation clients should implement the same
        # simple method and can be selected here from environment config later.
        normalized_target = (target_language or "").strip().lower()
        translated = self._dictionaries.get(normalized_target, {}).get(text)
        if translated:
            return translated
        label = target_language.strip() if target_language else "Translated"
        return f"[{label}] {text}"


class LibreTranslateProvider(BaseTranslationProvider):
    """Translation provider backed by a LibreTranslate-compatible REST API."""

    def __init__(self, base_url=None, api_key=None, timeout_seconds=None):
        self.base_url = (base_url or _setting("LIBRETRANSLATE_URL", "http://localhost:5001")).rstrip("/")
        self.api_key = api_key if api_key is not None else _setting("LIBRETRANSLATE_API_KEY", "")
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else _setting("TRANSLATION_TIMEOUT_SECONDS", 30)
        )

    def check_ready(self, source_language=None, target_language=None):
        """Confirm the service is reachable and required languages are installed."""
        target_code = normalize_language(target_language) if target_language else None
        if target_language and not target_code:
            return DiagnosticCheck(
                "translation",
                FAIL,
                f"Unsupported target language for translation: {target_language}",
            )

        request = Request(f"{self.base_url}/languages", method="GET")
        try:
            with urlopen(request, timeout=min(self.timeout_seconds, 5)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError):
            return DiagnosticCheck(
                "translation",
                FAIL,
                f"LibreTranslate is unavailable at {self.base_url}.",
            )

        available = sorted(
            str(language.get("code"))
            for language in payload
            if isinstance(language, dict) and language.get("code")
        )
        if target_code and target_code not in available:
            return DiagnosticCheck(
                "translation",
                FAIL,
                f"LibreTranslate does not have the {target_code} target language loaded.",
                {"available_languages": available},
            )
        source_code = normalize_language(source_language) if source_language else None
        if source_code and source_code not in available:
            return DiagnosticCheck(
                "translation",
                FAIL,
                f"LibreTranslate does not have the {source_code} source language loaded.",
                {"available_languages": available},
            )
        return DiagnosticCheck(
            "translation",
            PASS,
            "LibreTranslate is reachable and required languages are available.",
            {"provider": "libretranslate", "available_languages": available},
        )

    def translate(self, text, source_language, target_language):
        """Translate text using LibreTranslate's `/translate` endpoint."""
        target_code = normalize_language(target_language)
        if not target_code:
            raise ValueError(f"Unsupported target language for translation: {target_language}")

        source_code = normalize_language(source_language) or "auto"
        payload = {
            "q": text,
            "source": source_code,
            "target": target_code,
            "format": "text",
        }
        if self.api_key:
            payload["api_key"] = self.api_key

        data = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}/translate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LibreTranslate request failed: {message}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"LibreTranslate is unavailable at {self.base_url}") from exc

        translated_text = result.get("translatedText")
        if not translated_text:
            raise RuntimeError("LibreTranslate returned no translatedText value.")
        return translated_text


def get_translation_provider():
    """Select the configured translation provider.

    This is the extension point for a real translation service once credentials
    and provider-specific settings are introduced.
    """
    provider = str(_setting("TRANSLATION_PROVIDER", "libretranslate")).strip().lower()
    if provider in {"", "mock"}:
        return MockTranslationProvider()
    if provider in {"libretranslate", "libre_translate", "libre-translate"}:
        return LibreTranslateProvider()
    raise ValueError("Unknown TRANSLATION_PROVIDER. Use 'mock' or 'libretranslate'.")


def normalize_language(language):
    """Normalize common language labels to translation API language codes."""
    if not language:
        return None
    normalized = str(language).strip().lower().replace("_", "-")
    return _LANGUAGE_CODES.get(normalized)


def _setting(name, default):
    if has_app_context() and name in current_app.config:
        return current_app.config[name]
    return os.getenv(name, default)
