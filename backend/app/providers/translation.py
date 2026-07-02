import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app, has_app_context

from ..diagnostics import DiagnosticCheck, FAIL, PASS
from .translation_languages import language_catalog, normalize_language as _normalize_language


_MOCK_LANGUAGES = language_catalog()


class BaseTranslationProvider:
    """Interface for text translation implementations."""

    def get_languages(self):
        """Return languages currently available from this provider."""
        raise NotImplementedError

    def check_ready(self, source_language=None, target_language=None):
        """Return a provider-specific diagnostic readiness result."""
        raise NotImplementedError

    def translate(self, text, source_language, target_language):
        """Translate one subtitle segment while preserving segment timing."""
        raise NotImplementedError

    def translate_with_metadata(self, text, source_language, target_language):
        from .local_translation import TranslationOutput
        return TranslationOutput(
            self.translate(text, source_language, target_language),
            getattr(self, "provider_name", self.__class__.__name__.casefold()),
        )


class MockTranslationProvider(BaseTranslationProvider):
    """Small visible mock translator for local development and demos."""

    provider_name = "mock"

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

    def get_languages(self):
        return _MOCK_LANGUAGES

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

    provider_name = "libretranslate"

    def __init__(self, base_url=None, api_key=None, timeout_seconds=None):
        self.base_url = (base_url or _setting("LIBRETRANSLATE_URL", "http://localhost:5001")).rstrip("/")
        self.api_key = api_key if api_key is not None else _setting("LIBRETRANSLATE_API_KEY", "")
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else _setting("TRANSLATION_TIMEOUT_SECONDS", 30)
        )

    def get_languages(self):
        """Return LibreTranslate's live list of installed language models."""
        request = Request(f"{self.base_url}/languages", method="GET")
        try:
            with urlopen(request, timeout=min(self.timeout_seconds, 5)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise RuntimeError(
                f"LibreTranslate is unavailable at {self.base_url}"
            ) from exc

        languages = []
        for language in payload:
            if not isinstance(language, dict) or not language.get("code"):
                continue
            code = str(language["code"])
            languages.append(
                {
                    "code": code,
                    "name": str(language.get("name") or code),
                    "targets": [
                        str(target)
                        for target in language.get("targets", [])
                        if target
                    ],
                }
            )
        return sorted(languages, key=lambda language: language["name"].casefold())

    def check_ready(self, source_language=None, target_language=None):
        """Confirm the service is reachable and required languages are installed."""
        target_code = normalize_language(target_language) if target_language else None
        if target_language and not target_code:
            return DiagnosticCheck(
                "translation",
                FAIL,
                f"Unsupported target language for translation: {target_language}",
            )

        try:
            languages = self.get_languages()
        except RuntimeError:
            return DiagnosticCheck(
                "translation",
                FAIL,
                f"LibreTranslate is unavailable at {self.base_url}.",
            )

        available = sorted(language["code"] for language in languages)
        if target_code and target_code not in available:
            return DiagnosticCheck(
                "translation",
                FAIL,
                f"LibreTranslate does not have the {target_code} target language loaded.",
                {"available_languages": available},
            )
        source_code = normalize_language(source_language) if source_language else None
        if source_code and source_code != "auto" and source_code not in available:
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


class RoutedTranslationProvider(BaseTranslationProvider):
    """Choose a local translator from configurable source/target pair rules."""

    provider_name = "routed-local"

    def __init__(self, default_provider, overrides=None, providers=None):
        self.default_provider = str(default_provider or "nllb-ct2").strip().lower()
        self.overrides = overrides or {}
        self.providers = providers or {}

    def _provider(self, source_language=None, target_language=None):
        source = normalize_language(source_language) or "auto"
        target = normalize_language(target_language) or ""
        name = self.overrides.get((source, target), self.default_provider)
        if name not in self.providers:
            self.providers[name] = _provider_by_name(name)
        return self.providers[name]

    def get_languages(self):
        return self._provider().get_languages()

    def check_ready(self, source_language=None, target_language=None):
        return self._provider(source_language, target_language).check_ready(
            source_language, target_language
        )

    def translate(self, text, source_language, target_language):
        return self._provider(source_language, target_language).translate(
            text, source_language, target_language
        )

    def translate_with_metadata(self, text, source_language, target_language):
        provider = self._provider(source_language, target_language)
        if hasattr(provider, "translate_with_metadata"):
            return provider.translate_with_metadata(text, source_language, target_language)
        return super().translate_with_metadata(text, source_language, target_language)


def get_translation_provider():
    """Select the configured translation provider.

    This is the extension point for a real translation service once credentials
    and provider-specific settings are introduced.
    """
    provider = str(_setting("TRANSLATION_PROVIDER", "routed")).strip().lower()
    if provider in {"routed", "auto", "local-routed"}:
        return RoutedTranslationProvider(
            _setting("TRANSLATION_DEFAULT_PROVIDER", "nllb-ct2"),
            _parse_route_overrides(_setting("TRANSLATION_ROUTE_OVERRIDES", "")),
        )
    return _provider_by_name(provider)


def _provider_by_name(provider):
    provider = str(provider or "").strip().lower()
    if provider in {"", "mock"}:
        return MockTranslationProvider()
    if provider in {"libretranslate", "libre_translate", "libre-translate"}:
        return LibreTranslateProvider()
    if provider in {"nllb", "nllb-ct2", "local", "local-nllb"}:
        from .local_translation import FallbackTranslationProvider, LocalNllbTranslationProvider
        return FallbackTranslationProvider(
            LocalNllbTranslationProvider(),
            LibreTranslateProvider(),
        )
    raise ValueError(
        "Unknown TRANSLATION_PROVIDER. Use 'routed', 'mock', 'libretranslate', or 'nllb-ct2'."
    )


def _parse_route_overrides(value):
    output = {}
    for item in str(value or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            pair, provider = item.split("=", 1)
            source, target = pair.split(">", 1)
        except ValueError as exc:
            raise ValueError(
                "TRANSLATION_ROUTE_OVERRIDES must use source>target=provider entries."
            ) from exc
        source = normalize_language(source.strip()) or source.strip().lower()
        target = normalize_language(target.strip()) or target.strip().lower()
        provider = provider.strip().lower()
        if provider not in {"nllb", "nllb-ct2", "local", "local-nllb", "libretranslate", "libre_translate", "libre-translate", "mock"}:
            raise ValueError(f"Unknown routed translation provider: {provider}")
        output[(source, target)] = provider
    return output


def normalize_language(language):
    """Normalize common language labels to application language codes."""
    return _normalize_language(language)


def _setting(name, default):
    if has_app_context() and name in current_app.config:
        return current_app.config[name]
    return os.getenv(name, default)
