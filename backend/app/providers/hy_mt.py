"""HY-MT2 translation through a local KoboldCpp OpenAI-compatible endpoint."""

import re

from ..diagnostics import DiagnosticCheck, FAIL, PASS, WARN
from .local_llm import LocalLlmClient
from .local_translation import TranslationOutput, translation_quality_issue
from .translation_languages import get_language, language_catalog


_EXPLANATION_PREFIX = re.compile(
    r"^(?:here(?:'s| is) (?:the )?translation|translation|translated text)\s*[:：-]\s*",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^```[^\n]*\n?(.*?)\n?```$", re.DOTALL)


class HyMtKoboldTranslationProvider:
    provider_name = "hy-mt2-kobold"

    def __init__(
        self,
        base_url,
        api_key,
        model,
        timeout_seconds=60,
        temperature=0.7,
        top_p=0.6,
        top_k=20,
        repetition_penalty=1.05,
        max_tokens=256,
        retries=1,
        glossary=None,
        client=None,
        opener=None,
    ):
        self.model = str(model or "").strip()
        self.max_tokens = int(max_tokens)
        self.glossary = str(glossary or "").strip()
        self.client = client or LocalLlmClient(
            base_url=base_url,
            api_key=api_key,
            model=self.model,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            retries=retries,
            json_mode=False,
            opener=opener,
        )

    def get_languages(self):
        return language_catalog()

    def check_ready(self, source_language=None, target_language=None):
        for value in (source_language, target_language):
            if value and str(value).casefold() != "auto" and not get_language(value):
                return DiagnosticCheck(
                    "translation", FAIL, f"HY-MT2 has no configured language mapping for: {value}"
                )
        if not self.client.configured:
            return DiagnosticCheck(
                "translation", FAIL,
                "HY-MT2 KoboldCpp URL or model is not configured.",
                {"provider": self.provider_name},
            )
        try:
            models = self.client.check_ready()
        except Exception as exc:
            return DiagnosticCheck(
                "translation", FAIL,
                f"HY-MT2 KoboldCpp is unavailable: {exc}",
                {"provider": self.provider_name},
            )
        normalized_model = self.model.casefold()
        matched = not models or any(
            normalized_model in item.casefold() or item.casefold() in normalized_model
            for item in models
        )
        status = PASS if matched else WARN
        message = (
            "HY-MT2 is ready through KoboldCpp."
            if matched else
            "KoboldCpp is ready, but its reported model name differs from HY_MT_MODEL."
        )
        return DiagnosticCheck(
            "translation", status, message,
            {"provider": self.provider_name, "model": self.model, "reported_models": models},
        )

    def translate(self, text, source_language, target_language):
        return self.translate_with_metadata(text, source_language, target_language).text

    def translate_with_metadata(self, text, source_language, target_language):
        return self.translate_with_context(
            text, source_language, target_language, (), ()
        )

    def translate_with_context(
        self, text, source_language, target_language,
        context_before=(), context_after=(),
    ):
        prompt = build_hy_mt_prompt(
            text,
            source_language,
            target_language,
            context_before,
            context_after,
            self.glossary,
        )
        translated = self.client.request_text(
            [{"role": "user", "content": prompt}],
            self.max_tokens,
            validator=lambda value: validate_hy_mt_translation(value, text),
        )
        return TranslationOutput(translated, self.provider_name, self.model)


def build_hy_mt_prompt(
    source_text, source_language, target_language,
    context_before=(), context_after=(), glossary=None,
):
    source_name = _language_name(source_language)
    target_name = _language_name(target_language)
    sections = []
    context_lines = [
        *(f"Previous: {value}" for value in context_before if str(value).strip()),
        *(f"Next: {value}" for value in context_after if str(value).strip()),
    ]
    if context_lines:
        sections.append(
            "[Background Information]\n"
            + "\n".join(context_lines)
            + "\nUse this only to understand context; do not translate it."
        )
    terms = [line.strip() for line in str(glossary or "").splitlines() if line.strip()]
    if terms:
        sections.append(
            "[Terminology]\nPreserve these names and terms when applicable:\n"
            + "\n".join(f"- {term}" for term in terms)
        )
    sections.append(
        f"Translate the following text from {source_name} into {target_name}. "
        "Only output the translated result without labels or explanation.\n\n"
        f"[Source Text]\n{str(source_text).strip()}"
    )
    return "\n\n".join(sections)


def validate_hy_mt_translation(value, source_text):
    translated = str(value or "").strip()
    fenced = _FENCE.match(translated)
    if fenced:
        translated = fenced.group(1).strip()
    if _EXPLANATION_PREFIX.match(translated):
        raise ValueError("HY-MT2 returned an explanatory label instead of translation-only text.")
    issue = translation_quality_issue(translated, source_text)
    if issue:
        raise ValueError(f"HY-MT2 {issue}.")
    max_chars = max(160, len(str(source_text)) * 8 + 80)
    if len(translated) > max_chars:
        raise ValueError("HY-MT2 returned unreasonably long translation text.")
    if "[Source Text]" in translated or "[Background Information]" in translated:
        raise ValueError("HY-MT2 echoed prompt metadata.")
    return translated


def _language_name(value):
    language = get_language(value)
    if not language:
        raise ValueError(f"HY-MT2 has no configured language mapping for: {value}")
    return language.name.replace(" (Simplified)", "").replace(" (Traditional)", "")
