import json

import pytest

from app.providers import contextual_translation
from app.providers.contextual_translation import (
    ContextWord,
    OpenAICompatibleContextualTranslationProvider,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def words():
    return [
        ContextWord("w0", "Hello", 0.0, 0.5, "A", 0.9),
        ContextWord("w1", "world", 0.5, 1.0, "A", 0.8),
    ]


def test_accepts_koboldcpp_chat_shape_and_fenced_json(monkeypatch):
    content = '```json\n{"captions":[{"end_word_id":"w1","text":"Hola mundo"}]}\n```'
    monkeypatch.setattr(
        contextual_translation,
        "urlopen",
        lambda request, timeout: Response({"choices": [{"message": {"content": content}}]}),
    )
    provider = OpenAICompatibleContextualTranslationProvider(
        base_url="http://localhost:5002/v1", model="local", retries=0
    )

    captions = provider.translate_window(words(), [], "en", "es")

    assert captions[0].translated_text == "Hola mundo"
    assert captions[0].start_word_id == "w0"
    assert captions[0].end_word_id == "w1"


def test_requests_explicit_generation_budget(monkeypatch):
    captured = {}

    def respond(request, timeout):
        captured.update(json.loads(request.data.decode()))
        return Response({"choices": [{"message": {"content": '{"captions":[{"end_word_id":"w1","text":"Hola mundo"}]}'}}]})

    monkeypatch.setattr(contextual_translation, "urlopen", respond)
    provider = OpenAICompatibleContextualTranslationProvider(
        base_url="http://localhost:5002/v1", model="local", max_tokens=1234, retries=0
    )

    provider.translate_window(words(), [], "en", "es")

    assert captured["max_tokens"] == 1234


def test_infers_each_start_from_the_previous_end(monkeypatch):
    content = '{"captions":[{"end_word_id":"w0","text":"Hola"},{"end_word_id":"w1","text":"mundo"}]}'
    monkeypatch.setattr(
        contextual_translation,
        "urlopen",
        lambda request, timeout: Response({"choices": [{"message": {"content": content}}]}),
    )
    provider = OpenAICompatibleContextualTranslationProvider(
        base_url="http://localhost:5002/v1", model="local", retries=0
    )

    captions = provider.translate_window(words(), [], "en", "es")

    assert [(item.start_word_id, item.end_word_id) for item in captions] == [("w0", "w0"), ("w1", "w1")]


@pytest.mark.parametrize(
    "captions",
    [
        [{"start_word_id": "w1", "end_word_id": "w1", "text": "mundo"}],
        [{"start_word_id": "missing", "end_word_id": "w1", "text": "Hola"}],
        [{"start_word_id": "w0", "end_word_id": "w1", "text": "x" * 85}],
    ],
)
def test_rejects_missing_unknown_or_oversized_output(monkeypatch, captions):
    content = json.dumps({"target_language": "es", "captions": captions})
    monkeypatch.setattr(
        contextual_translation,
        "urlopen",
        lambda request, timeout: Response({"choices": [{"message": {"content": content}}]}),
    )
    provider = OpenAICompatibleContextualTranslationProvider(
        base_url="http://localhost:5002/v1", model="local", retries=0
    )

    with pytest.raises(RuntimeError):
        provider.translate_window(words(), [], "en", "es")


def test_rejects_caption_that_crosses_speakers(monkeypatch):
    mixed = [words()[0], ContextWord("w1", "there", 0.5, 1.0, "B")]
    content = '{"target_language":"es","captions":[{"start_word_id":"w0","end_word_id":"w1","text":"Hola"}]}'
    monkeypatch.setattr(
        contextual_translation,
        "urlopen",
        lambda request, timeout: Response({"choices": [{"message": {"content": content}}]}),
    )
    provider = OpenAICompatibleContextualTranslationProvider(
        base_url="http://localhost:5002/v1", model="local", retries=0
    )

    with pytest.raises(RuntimeError, match="speaker"):
        provider.translate_window(mixed, [], "en", "es")
