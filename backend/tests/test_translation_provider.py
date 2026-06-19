import json
from urllib.error import URLError

import pytest

from app.providers import translation
from app.providers.translation import (
    LibreTranslateProvider,
    MockTranslationProvider,
    get_translation_provider,
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


def test_get_translation_provider_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "other")

    with pytest.raises(ValueError, match="Unknown TRANSLATION_PROVIDER"):
        get_translation_provider()


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
