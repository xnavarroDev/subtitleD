import json
from urllib.error import URLError

import pytest

from app.providers import translation
from app.providers.translation import (
    LibreTranslateProvider,
    MockTranslationProvider,
    get_translation_provider,
    normalize_project_translation_provider,
    RoutedTranslationProvider,
    normalize_language,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_get_translation_provider_can_select_mock(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "mock")

    provider = get_translation_provider()

    assert isinstance(provider, MockTranslationProvider)


def test_get_translation_provider_can_select_libretranslate(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "libretranslate")

    provider = get_translation_provider()

    assert isinstance(provider, LibreTranslateProvider)


def test_get_translation_provider_can_use_explicit_project_provider(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "mock")

    provider = get_translation_provider(provider_name="libre_translate")

    assert isinstance(provider, LibreTranslateProvider)


def test_get_translation_provider_can_select_local_nllb_with_fallback(monkeypatch):
    from app.providers.local_translation import FallbackTranslationProvider

    monkeypatch.setenv("TRANSLATION_PROVIDER", "nllb-ct2")

    assert isinstance(get_translation_provider(), FallbackTranslationProvider)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("hy-mt2", "hy-mt2-kobold"),
        ("koboldcpp", "hy-mt2-kobold"),
        ("nllb", "nllb-ct2"),
        ("local-nllb", "nllb-ct2"),
        ("libre-translate", "libretranslate"),
        ("mock", None),
        ("routed", None),
        ("", None),
    ],
)
def test_normalize_project_translation_provider(value, expected):
    assert normalize_project_translation_provider(value) == expected


def test_get_translation_provider_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "other")

    with pytest.raises(ValueError, match="Unknown TRANSLATION_PROVIDER"):
        get_translation_provider()


def test_routed_provider_avoids_primary_for_configured_language_pair():
    calls = []

    class Provider:
        def __init__(self, name): self.provider_name = name
        def translate(self, text, source, target):
            calls.append(self.provider_name)
            return f"{self.provider_name}:{text}"
        def get_languages(self): return []
        def check_ready(self, *args): return None

    routed = RoutedTranslationProvider(
        "nllb-ct2",
        {("ja", "en"): "libretranslate"},
        {
            "nllb-ct2": Provider("nllb-ct2"),
            "libretranslate": Provider("libretranslate"),
        },
    )

    assert routed.translate("source", "ja", "en") == "libretranslate:source"
    assert routed.translate("source", "tl", "en") == "nllb-ct2:source"
    assert calls == ["libretranslate", "nllb-ct2"]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("English", "en"),
        ("Spanish", "es"),
        ("french", "fr"),
        ("EN", "en"),
        ("uk", "uk"),
        ("pt-br", "pt-br"),
        ("auto", "auto"),
        ("made up language", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_language(label, expected):
    assert normalize_language(label) == expected


def test_libretranslate_provider_posts_translation_request(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse({"translatedText": "Hola mundo"})

    monkeypatch.setattr(translation, "urlopen", fake_urlopen)
    provider = LibreTranslateProvider(
        base_url="http://translator:5000",
        api_key="secret",
        timeout_seconds=7,
    )

    result = provider.translate("Hello world", "English", "Spanish")

    assert result == "Hola mundo"
    request, timeout = requests[0]
    assert request.full_url == "http://translator:5000/translate"
    assert timeout == 7
    assert request.headers["Content-type"] == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "q": "Hello world",
        "source": "en",
        "target": "es",
        "format": "text",
        "api_key": "secret",
    }


def test_libretranslate_readiness_checks_required_languages(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url == "http://translator:5000/languages"
        assert timeout == 5
        return FakeResponse(
            [
                {"code": "en", "name": "English"},
                {"code": "es", "name": "Spanish"},
            ]
        )

    monkeypatch.setattr(translation, "urlopen", fake_urlopen)
    provider = LibreTranslateProvider(
        base_url="http://translator:5000",
        timeout_seconds=30,
    )

    result = provider.check_ready("English", "Spanish")

    assert result.status == "pass"
    assert result.details["available_languages"] == ["en", "es"]


def test_libretranslate_readiness_maps_app_chinese_code_to_libretranslate(monkeypatch):
    monkeypatch.setattr(
        translation,
        "urlopen",
        lambda request, timeout: FakeResponse(
            [
                {"code": "en", "name": "English"},
                {"code": "zh-Hans", "name": "Chinese"},
                {"code": "zh-Hant", "name": "Chinese (traditional)"},
            ]
        ),
    )
    provider = LibreTranslateProvider(base_url="http://translator:5000")

    simplified = provider.check_ready("zh", "en")
    traditional = provider.check_ready("zh-tw", "en")
    target = provider.check_ready("en", "Chinese")

    assert simplified.status == "pass"
    assert traditional.status == "pass"
    assert target.status == "pass"


def test_libretranslate_provider_returns_installed_languages(monkeypatch):
    monkeypatch.setattr(
        translation,
        "urlopen",
        lambda request, timeout: FakeResponse(
            [
                {"code": "es", "name": "Spanish", "targets": ["en"]},
                {"code": "en", "name": "English", "targets": ["es"]},
            ]
        ),
    )
    provider = LibreTranslateProvider(base_url="http://translator:5000")

    assert provider.get_languages() == [
        {"code": "en", "name": "English", "targets": ["es"]},
        {"code": "es", "name": "Spanish", "targets": ["en"]},
    ]


def test_libretranslate_provider_exposes_canonical_app_language_codes(monkeypatch):
    monkeypatch.setattr(
        translation,
        "urlopen",
        lambda request, timeout: FakeResponse(
            [
                {
                    "code": "zh-Hans",
                    "name": "Chinese (Simplified)",
                    "targets": ["en", "zh-Hant"],
                },
                {
                    "code": "zh-Hant",
                    "name": "Chinese (Traditional)",
                    "targets": ["en", "zh-Hans"],
                },
                {"code": "en", "name": "English", "targets": ["zh-Hans"]},
                {"code": "nb", "name": "Norwegian", "targets": ["en"]},
                {"code": "pt-BR", "name": "Portuguese", "targets": ["en"]},
            ]
        ),
    )
    provider = LibreTranslateProvider(base_url="http://translator:5000")

    assert provider.get_languages() == [
        {
            "code": "zh",
            "name": "Chinese (Simplified)",
            "targets": ["en", "zh-tw"],
        },
        {
            "code": "zh-tw",
            "name": "Chinese (Traditional)",
            "targets": ["en", "zh"],
        },
        {"code": "en", "name": "English", "targets": ["zh"]},
        {"code": "no", "name": "Norwegian", "targets": ["en"]},
        {"code": "pt-br", "name": "Portuguese", "targets": ["en"]},
    ]


def test_libretranslate_readiness_rejects_unsupported_language_pair(monkeypatch):
    monkeypatch.setattr(
        translation,
        "urlopen",
        lambda request, timeout: FakeResponse(
            [
                {"code": "de", "name": "German", "targets": ["en"]},
                {"code": "en", "name": "English", "targets": ["es"]},
                {"code": "es", "name": "Spanish", "targets": ["en"]},
            ]
        ),
    )
    provider = LibreTranslateProvider(base_url="http://translator:5000")

    result = provider.check_ready("en", "de")

    assert result.status == "fail"
    assert result.message == "LibreTranslate does not support translation from en to de."
    assert result.details["available_targets"] == ["es"]


def test_libretranslate_readiness_rejects_missing_target_language(monkeypatch):
    monkeypatch.setattr(
        translation,
        "urlopen",
        lambda request, timeout: FakeResponse([{"code": "en", "name": "English"}]),
    )
    provider = LibreTranslateProvider(base_url="http://translator:5000")

    result = provider.check_ready("English", "Spanish")

    assert result.status == "fail"
    assert "es" in result.message


def test_libretranslate_provider_uses_auto_for_unknown_source(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse({"translatedText": "Hola"})

    monkeypatch.setattr(translation, "urlopen", fake_urlopen)
    provider = LibreTranslateProvider(base_url="http://translator:5000")

    provider.translate("Hello", "Unknown", "Spanish")

    assert json.loads(requests[0].data.decode("utf-8"))["source"] == "auto"


def test_libretranslate_provider_posts_libretranslate_chinese_codes(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse({"translatedText": "Hello"})

    monkeypatch.setattr(translation, "urlopen", fake_urlopen)
    provider = LibreTranslateProvider(base_url="http://translator:5000")

    provider.translate("你好", "Chinese", "English")

    payload = json.loads(requests[0].data.decode("utf-8"))
    assert payload["source"] == "zh-Hans"
    assert payload["target"] == "en"


def test_libretranslate_provider_rejects_unknown_target_language():
    provider = LibreTranslateProvider(base_url="http://translator:5000")

    with pytest.raises(ValueError, match="Unsupported target language"):
        provider.translate("Hello", "English", "Klingon")


def test_libretranslate_provider_reports_unavailable_service(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("offline")

    monkeypatch.setattr(translation, "urlopen", fake_urlopen)
    provider = LibreTranslateProvider(base_url="http://translator:5000")

    with pytest.raises(RuntimeError, match="LibreTranslate is unavailable"):
        provider.translate("Hello", "English", "Spanish")
