"""Application language registry shared by local and HTTP translation providers."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TranslationLanguage:
    code: str
    name: str
    nllb_code: str
    aliases: tuple[str, ...] = ()


LANGUAGES = (
    TranslationLanguage("ar", "Arabic", "arb_Arab", ("arabic",)),
    TranslationLanguage("bg", "Bulgarian", "bul_Cyrl", ("bulgarian",)),
    TranslationLanguage("zh", "Chinese (Simplified)", "zho_Hans", ("chinese", "zh-cn", "zh-hans")),
    TranslationLanguage("zh-tw", "Chinese (Traditional)", "zho_Hant", ("traditional chinese", "zh-hant")),
    TranslationLanguage("cs", "Czech", "ces_Latn", ("czech",)),
    TranslationLanguage("da", "Danish", "dan_Latn", ("danish",)),
    TranslationLanguage("nl", "Dutch", "nld_Latn", ("dutch",)),
    TranslationLanguage("en", "English", "eng_Latn", ("english",)),
    TranslationLanguage("fi", "Finnish", "fin_Latn", ("finnish",)),
    TranslationLanguage("fr", "French", "fra_Latn", ("french",)),
    TranslationLanguage("de", "German", "deu_Latn", ("german",)),
    TranslationLanguage("el", "Greek", "ell_Grek", ("greek",)),
    TranslationLanguage("he", "Hebrew", "heb_Hebr", ("hebrew",)),
    TranslationLanguage("hi", "Hindi", "hin_Deva", ("hindi",)),
    TranslationLanguage("hu", "Hungarian", "hun_Latn", ("hungarian",)),
    TranslationLanguage("id", "Indonesian", "ind_Latn", ("indonesian",)),
    TranslationLanguage("it", "Italian", "ita_Latn", ("italian",)),
    TranslationLanguage("ja", "Japanese", "jpn_Jpan", ("japanese",)),
    TranslationLanguage("ko", "Korean", "kor_Hang", ("korean",)),
    TranslationLanguage("no", "Norwegian", "nob_Latn", ("norwegian", "nb")),
    TranslationLanguage("pl", "Polish", "pol_Latn", ("polish",)),
    TranslationLanguage("pt", "Portuguese", "por_Latn", ("portuguese",)),
    TranslationLanguage("pt-br", "Portuguese (Brazil)", "por_Latn", ("brazilian portuguese",)),
    TranslationLanguage("ro", "Romanian", "ron_Latn", ("romanian",)),
    TranslationLanguage("ru", "Russian", "rus_Cyrl", ("russian",)),
    TranslationLanguage("sk", "Slovak", "slk_Latn", ("slovak",)),
    TranslationLanguage("es", "Spanish", "spa_Latn", ("spanish",)),
    TranslationLanguage("sv", "Swedish", "swe_Latn", ("swedish",)),
    TranslationLanguage("tl", "Tagalog", "tgl_Latn", ("tagalog", "fil", "filipino")),
    TranslationLanguage("th", "Thai", "tha_Thai", ("thai",)),
    TranslationLanguage("tr", "Turkish", "tur_Latn", ("turkish",)),
    TranslationLanguage("uk", "Ukrainian", "ukr_Cyrl", ("ukrainian",)),
    TranslationLanguage("vi", "Vietnamese", "vie_Latn", ("vietnamese",)),
)

_BY_CODE = {item.code: item for item in LANGUAGES}
_BY_ALIAS = {
    alias.casefold(): item
    for item in LANGUAGES
    for alias in (item.code, item.name, *item.aliases)
}
_LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")


def normalize_language(language):
    if not language:
        return None
    normalized = str(language).strip().casefold().replace("_", "-")
    if normalized == "auto":
        return "auto"
    known = _BY_ALIAS.get(normalized)
    if known:
        return known.code
    return normalized if _LANGUAGE_CODE_PATTERN.fullmatch(normalized) else None


def get_language(language):
    code = normalize_language(language)
    return _BY_CODE.get(code)


def nllb_language_code(language):
    item = get_language(language)
    if not item:
        raise ValueError(f"NLLB does not have a configured language mapping for: {language}")
    return item.nllb_code


def language_catalog():
    codes = [item.code for item in LANGUAGES]
    return [
        {
            "code": item.code,
            "name": item.name,
            "targets": [code for code in codes if code != item.code],
        }
        for item in LANGUAGES
    ]
