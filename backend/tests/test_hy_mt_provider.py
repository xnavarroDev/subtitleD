import json

import pytest

from app.providers.hy_mt import (
    HyMtKoboldTranslationProvider,
    build_hy_mt_prompt,
    validate_hy_mt_translation,
)
from app.providers.local_llm import LocalLlmClient


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_local_client_sends_kobold_sampling_controls():
    captured = {}

    def opener(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response({"choices": [{"message": {"content": "Natural translation"}}]})

    client = LocalLlmClient(
        "http://localhost:5002/v1", "", "Hy-MT2-7B",
        timeout_seconds=30, temperature=.7, top_p=.6, top_k=20,
        repetition_penalty=1.05, retries=0, opener=opener,
    )

    assert client.request_text([{"role": "user", "content": "Translate"}], 256) == "Natural translation"
    assert captured["payload"]["temperature"] == .7
    assert captured["payload"]["top_p"] == .6
    assert captured["payload"]["top_k"] == 20
    assert captured["payload"]["rep_pen"] == 1.05
    assert captured["payload"]["repetition_penalty"] == 1.05
    assert captured["payload"]["max_tokens"] == 256


def test_hy_mt_prompt_keeps_context_and_source_separate():
    prompt = build_hy_mt_prompt(
        "今日はありがとう", "ja", "en",
        ("前の文",), ("次の文",), "Saiki\nTeruhashi",
    )

    assert "Previous: 前の文" in prompt
    assert "Next: 次の文" in prompt
    assert "do not translate it" in prompt
    assert "Saiki" in prompt
    assert "from Japanese into English" in prompt
    assert prompt.endswith("[Source Text]\n今日はありがとう")


def test_hy_mt_provider_returns_plain_translation_with_provenance():
    calls = {}

    class Client:
        configured = True

        def request_text(self, messages, max_tokens, validator=None, **_kwargs):
            calls["messages"] = messages
            calls["max_tokens"] = max_tokens
            return validator("Thank you for today.")

    provider = HyMtKoboldTranslationProvider(
        "http://localhost:5002/v1", "", "Hy-MT2-7B",
        max_tokens=256, client=Client(),
    )
    output = provider.translate_with_context(
        "今日はありがとう", "ja", "en", ("それでは",), ()
    )

    assert output.text == "Thank you for today."
    assert output.provider == "hy-mt2-kobold"
    assert output.model == "Hy-MT2-7B"
    assert calls["max_tokens"] == 256
    assert "Previous: それでは" in calls["messages"][0]["content"]


def test_hy_mt_validation_rejects_explanations_and_repetition():
    with pytest.raises(ValueError, match="explanatory"):
        validate_hy_mt_translation("Translation: Thank you.", "ありがとう")
    with pytest.raises(ValueError, match="repetition"):
        validate_hy_mt_translation("hey hey hey hey hey hey", "こんにちは")

