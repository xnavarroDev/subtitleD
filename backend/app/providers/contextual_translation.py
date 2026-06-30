import json
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app, has_app_context

from ..diagnostics import DiagnosticCheck, FAIL, PASS
from ..utils.captions import normalize_caption_text

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class ContextWord:
    id: str
    text: str
    start_time: float
    end_time: float
    speaker_label: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class ContextCaption:
    start_word_id: str
    end_word_id: str
    translated_text: str


class OpenAICompatibleContextualTranslationProvider:
    def __init__(self, base_url=None, api_key=None, model=None, timeout_seconds=None, temperature=None, max_tokens=None, max_chars=None, max_duration=None, retries=0):
        self.base_url = str(base_url if base_url is not None else _setting("LLM_BASE_URL", "")).strip()
        self.api_key = str(api_key if api_key is not None else _setting("LLM_API_KEY", "")).strip()
        self.model = str(model if model is not None else _setting("LLM_MODEL", "")).strip()
        self.timeout_seconds = float(timeout_seconds if timeout_seconds is not None else _setting("LLM_TIMEOUT_SECONDS", 60))
        self.temperature = float(temperature if temperature is not None else _setting("LLM_TEMPERATURE", 0.1))
        self.max_tokens = int(max_tokens if max_tokens is not None else _setting("LLM_MAX_TOKENS", 256))
        self.max_chars = int(max_chars if max_chars is not None else _setting("CAPTION_MAX_CHARS", 84))
        self.max_duration = float(max_duration if max_duration is not None else _setting("CAPTION_MAX_DURATION_SECONDS", 6))
        self.retries = int(retries)

    @property
    def chat_url(self):
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"

    def check_ready(self):
        if not self.base_url or not self.model:
            return DiagnosticCheck("contextual_translation", FAIL, "Contextual LLM base URL or model is missing.")
        models_url = self.chat_url.rsplit("/chat/completions", 1)[0] + "/models"
        try:
            with urlopen(Request(models_url, headers=self._headers()), timeout=min(self.timeout_seconds, 5)) as response:
                response.read()
        except (HTTPError, URLError, TimeoutError, OSError):
            return DiagnosticCheck("contextual_translation", FAIL, f"Contextual LLM is unavailable at {self.base_url}.")
        return DiagnosticCheck("contextual_translation", PASS, "Contextual LLM translation is ready.", {"model": self.model})

    def translate_window(self, words, previous_captions, source_language, target_language):
        last_error = None
        for _ in range(self.retries + 1):
            try:
                return self._validate(self._request(words, previous_captions, source_language, target_language), words, target_language)
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = exc
        raise RuntimeError(f"Contextual translation failed: {last_error}") from last_error

    def _request(self, words, previous_captions, source_language, target_language):
        system = (
            "Translate timestamped transcript words into natural subtitle captions. Previous captions are context only. "
            "The first caption starts at the first supplied word. Every later caption starts after the prior end_word_id. "
            "The final end_word_id MUST equal the final supplied word ID. Use only supplied IDs, in increasing order. "
            "Each caption must stay within one speaker, "
            f"last no more than {self.max_duration:g} seconds, and contain at most {self.max_chars} characters. Preserve meaning, names, and numbers. "
            'Return JSON only: {"captions":[{"end_word_id":"w000005","text":"translation"}]}. '
            "Do not return start_word_id, commentary, or Markdown."
        )
        payload_words = [{"id": w.id, "text": w.text, "start": w.start_time, "end": w.end_time, "speaker": w.speaker_label} for w in words]
        user = json.dumps({"source_language": source_language, "target_language": target_language, "previous_captions": previous_captions, "words": payload_words}, ensure_ascii=False)
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        request = Request(self.chat_url, data=json.dumps(payload).encode("utf-8"), headers=self._headers(), method="POST")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            result = json.loads(response.read().decode("utf-8"))
        choices = result.get("choices") or []
        if not choices:
            raise ValueError("LLM returned no choices.")
        content = (choices[0].get("message") or {}).get("content") or choices[0].get("text")
        if not content:
            raise ValueError("LLM returned no content.")
        return content

    def _validate(self, content, words, target_language):
        result = _parse_json(content)
        declared_language = str(result.get("target_language", "")).strip()
        if declared_language and declared_language.casefold() != str(target_language).strip().casefold():
            raise ValueError("LLM response target language did not match.")
        raw_captions = result.get("captions")
        if not isinstance(raw_captions, list) or not raw_captions:
            raise ValueError("LLM returned no captions.")
        index_by_id = {word.id: index for index, word in enumerate(words)}
        expected_index, captions = 0, []
        for raw in raw_captions:
            if not isinstance(raw, dict) or expected_index >= len(words):
                raise ValueError("LLM returned missing, duplicated, or reordered word IDs.")
            end_id = str(raw.get("end_word_id"))
            if end_id not in index_by_id:
                raise ValueError("LLM returned an unknown word ID.")
            start, end = expected_index, index_by_id[end_id]
            supplied_start = raw.get("start_word_id")
            if supplied_start is not None and str(supplied_start) != words[start].id:
                raise ValueError("LLM returned missing, duplicated, or reordered word IDs.")
            if end < start:
                raise ValueError("LLM returned missing, duplicated, or reordered word IDs.")
            span = words[start:end + 1]
            if span[-1].end_time - span[0].start_time > self.max_duration:
                raise ValueError("LLM returned an oversized caption duration.")
            if len({w.speaker_label for w in span if w.speaker_label}) > 1:
                raise ValueError("LLM crossed a speaker boundary.")
            text = normalize_caption_text(raw.get("text"))
            if not text or len(text) > self.max_chars:
                raise ValueError("LLM returned empty or oversized caption text.")
            captions.append(ContextCaption(words[start].id, end_id, text))
            expected_index = end + 1
        if expected_index != len(words):
            raise ValueError("LLM did not cover every source word.")
        return captions

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


def get_contextual_translation_provider():
    provider = str(_setting("CONTEXTUAL_TRANSLATION_PROVIDER", "openai-compatible")).strip().lower()
    if provider in {"openai", "openai-compatible", "openai_compatible", "koboldcpp"}:
        return OpenAICompatibleContextualTranslationProvider()
    raise ValueError("Unknown CONTEXTUAL_TRANSLATION_PROVIDER. Use 'openai-compatible'.")


def _parse_json(content):
    stripped = content.strip()
    fenced = _JSON_FENCE.search(stripped)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(stripped)
    if "{" in stripped and "}" in stripped:
        candidates.append(stripped[stripped.find("{"):stripped.rfind("}") + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    raise ValueError("LLM response did not contain valid JSON.")


def _setting(name, default):
    if has_app_context() and name in current_app.config:
        return current_app.config[name]
    return os.getenv(name, default)
