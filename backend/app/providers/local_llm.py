"""Shared OpenAI-compatible client for optional local LLM features."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


class LocalLlmClient:
    def __init__(
        self,
        base_url,
        api_key,
        model,
        timeout_seconds=60,
        temperature=0,
        top_p=None,
        top_k=None,
        repetition_penalty=None,
        retries=1,
        json_mode=False,
        opener=None,
    ):
        self.base_url = str(base_url or "").strip()
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip()
        self.timeout_seconds = float(timeout_seconds)
        self.temperature = float(temperature)
        self.top_p = None if top_p is None else float(top_p)
        self.top_k = None if top_k is None else int(top_k)
        self.repetition_penalty = (
            None if repetition_penalty is None else float(repetition_penalty)
        )
        self.retries = max(int(retries), 0)
        self.json_mode = bool(json_mode)
        self.opener = opener or urlopen

    @property
    def chat_url(self):
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"

    @property
    def models_url(self):
        return self.chat_url.rsplit("/chat/completions", 1)[0] + "/models"

    @property
    def configured(self):
        return bool(self.base_url and self.model)

    def check_ready(self):
        if not self.configured:
            raise RuntimeError("Local LLM base URL or model is missing.")
        with self.opener(
            Request(self.models_url, headers=self._headers()),
            timeout=min(self.timeout_seconds, 5),
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [
            str(item.get("id")) for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]

    def request_json(self, messages, max_tokens):
        return self.request_text(messages, max_tokens, validator=parse_json, json_mode=True)

    def request_text(
        self, messages, max_tokens, validator=None, json_mode=False, extra_body=None,
    ):
        last_error = None
        for _ in range(self.retries + 1):
            try:
                value = self._request(
                    messages, max_tokens, json_mode=json_mode, extra_body=extra_body
                )
                return validator(value) if validator else value
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = exc
        raise RuntimeError(f"Local LLM request failed: {last_error}") from last_error

    def _request(self, messages, max_tokens, json_mode=False, extra_body=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": int(max_tokens),
            "stream": False,
        }
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.top_k is not None:
            payload["top_k"] = self.top_k
        if self.repetition_penalty is not None:
            # KoboldCpp accepts its native name as an OpenAI request extension.
            payload["rep_pen"] = self.repetition_penalty
            payload["repetition_penalty"] = self.repetition_penalty
        if extra_body:
            payload.update(extra_body)
        if json_mode or self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = Request(
            self.chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        with self.opener(request, timeout=self.timeout_seconds) as response:
            result = json.loads(response.read().decode("utf-8"))
        choices = result.get("choices") or []
        if not choices:
            raise ValueError("LLM returned no choices.")
        content = (choices[0].get("message") or {}).get("content") or choices[0].get("text")
        if not content:
            raise ValueError("LLM returned no content.")
        return content

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


def parse_json(content):
    stripped = str(content or "").strip()
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


def get_local_llm_client(opener=None):
    """Build the shared optional local-LLM client from Flask configuration."""
    from flask import current_app

    return LocalLlmClient(
        current_app.config.get("LLM_BASE_URL", ""),
        current_app.config.get("LLM_API_KEY", ""),
        current_app.config.get("LLM_MODEL", ""),
        current_app.config.get("LLM_TIMEOUT_SECONDS", 60),
        current_app.config.get("LLM_TEMPERATURE", 0),
        retries=current_app.config.get("LLM_RETRIES", 1),
        json_mode=current_app.config.get("LLM_JSON_MODE", False),
        opener=opener,
    )
