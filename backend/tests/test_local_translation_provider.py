import json
from types import SimpleNamespace

from app.providers.local_translation import (
    FallbackTranslationProvider,
    LocalNllbTranslationProvider,
    TranslationOutput,
    translation_quality_issue,
)
from app.providers.translation_languages import nllb_language_code, normalize_language


def _installed_dirs(tmp_path):
    model = tmp_path / "model"
    tokenizer = tmp_path / "tokenizer"
    model.mkdir()
    tokenizer.mkdir()
    (model / "model.bin").write_bytes(b"model")
    (model / "subtitleD-model.json").write_text(json.dumps({
        "model": "facebook/nllb-200-distilled-600M",
        "revision": "b3bbac6cd67efa90e0fcbe4c882ec79cfd782a17",
    }), encoding="utf-8")
    (tokenizer / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    return model, tokenizer


def test_multilingual_registry_maps_application_codes_to_nllb_tokens():
    assert normalize_language("Japanese") == "ja"
    assert normalize_language("pt-br") == "pt-br"
    assert nllb_language_code("ja") == "jpn_Jpan"
    assert nllb_language_code("Tagalog") == "tgl_Latn"
    assert nllb_language_code("zh-tw") == "zho_Hant"


def test_local_provider_reports_explicit_setup_when_model_is_missing(tmp_path):
    provider = LocalNllbTranslationProvider(
        model_dir=tmp_path / "missing-model",
        tokenizer_dir=tmp_path / "missing-tokenizer",
    )

    result = provider.check_ready("ja", "en")

    assert result.status == "fail"
    assert "setup-local-translation" in result.message


def test_local_provider_translates_with_pinned_local_runtime(tmp_path):
    model_dir, tokenizer_dir = _installed_dirs(tmp_path)
    calls = {}

    class Tokenizer:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls["tokenizer"] = (path, kwargs)
            return cls()

        def encode(self, text, **kwargs):
            calls["encoded"] = (text, kwargs)
            return [1, 2]

        def convert_ids_to_tokens(self, ids):
            return ["hello", "world"] if ids == [1, 2] else ids

        def convert_tokens_to_ids(self, tokens):
            return tokens

        def decode(self, tokens, **kwargs):
            return "Local translation"

    class Translator:
        def __init__(self, path, **kwargs):
            calls["translator"] = (path, kwargs)

        def translate_batch(self, sources, **kwargs):
            calls["batch"] = (sources, kwargs)
            return [SimpleNamespace(hypotheses=[["eng_Latn", "translated"]])]

    provider = LocalNllbTranslationProvider(
        model_dir=model_dir,
        tokenizer_dir=tokenizer_dir,
        translator_class=Translator,
        tokenizer_class=Tokenizer,
    )

    output = provider.translate_with_metadata("こんにちは", "ja", "en")

    assert output.text == "Local translation"
    assert output.provider == "nllb-ct2"
    assert output.model == (
        "facebook/nllb-200-distilled-600M@"
        "b3bbac6cd67efa90e0fcbe4c882ec79cfd782a17"
    )
    assert calls["batch"][1]["target_prefix"] == [["eng_Latn"]]
    assert calls["tokenizer"][1]["src_lang"] == "jpn_Jpan"
    assert calls["tokenizer"][1]["local_files_only"] is True


def test_local_provider_falls_back_to_libre_with_provenance():
    class Broken:
        provider_name = "nllb-ct2"

        def translate_with_metadata(self, *args):
            raise RuntimeError("model unavailable")

        def get_languages(self):
            return []

        def check_ready(self, *args):
            return SimpleNamespace(status="fail", message="missing", details={})

    class Libre:
        provider_name = "libretranslate"

        def translate(self, *args):
            return "Fallback text"

    output = FallbackTranslationProvider(Broken(), Libre()).translate_with_metadata(
        "source", "ja", "en"
    )

    assert output == TranslationOutput(
        "Fallback text",
        "libretranslate",
        warning="nllb-ct2 translation failed; libretranslate fallback was used: model unavailable",
    )


def test_quality_gate_rejects_degenerate_repetition_but_not_natural_text():
    assert "repetition" in translation_quality_issue(
        "Hey, hey, hey, hey, hey, hey, hey!", "source"
    )
    assert translation_quality_issue(
        "Don't talk to me all of a sudden!", "source"
    ) is None


def test_source_languages_share_one_ctranslate2_translator(tmp_path):
    model_dir, tokenizer_dir = _installed_dirs(tmp_path)
    counts = {"translators": 0, "tokenizers": []}

    class Tokenizer:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            counts["tokenizers"].append(kwargs["src_lang"])
            return cls()
        def encode(self, text, **kwargs): return [1]
        def convert_ids_to_tokens(self, ids): return ["x"]
        def convert_tokens_to_ids(self, tokens): return [1]
        def decode(self, tokens, **kwargs): return "translated"

    class Translator:
        def __init__(self, *args, **kwargs): counts["translators"] += 1
        def translate_batch(self, sources, **kwargs):
            return [SimpleNamespace(hypotheses=[[kwargs["target_prefix"][0][0], "x"]])]

    LocalNllbTranslationProvider._translator_cache.clear()
    LocalNllbTranslationProvider._tokenizer_cache.clear()
    provider = LocalNllbTranslationProvider(
        model_dir=model_dir, tokenizer_dir=tokenizer_dir,
        translator_class=Translator, tokenizer_class=Tokenizer,
    )
    provider.translate("hola", "es", "en")
    provider.translate("bonjour", "fr", "en")

    assert counts["translators"] == 1
    assert counts["tokenizers"] == ["spa_Latn", "fra_Latn"]
