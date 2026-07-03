from app.providers.transcription import TranscriptWord
from app.utils.caption_translation import iter_deterministic_translation


def timed_words(count=12):
    return [
        TranscriptWord(
            f"word{i}", float(i), float(i) + 0.5, "A", 0.9 - i * 0.01,
        )
        for i in range(count)
    ]


class Translator:
    def __init__(self, prefix="L:"):
        self.prefix = prefix
        self.calls = []

    def translate(self, text, source, target):
        self.calls.append((text, source, target))
        return f"{self.prefix}{text}"


def flatten(batches):
    return [item for batch, _completed, _warning in batches for item in batch]


def test_deterministic_pipeline_covers_every_word_without_llm():
    translator = Translator()
    batches = list(iter_deterministic_translation(
        timed_words(8), translator, "en", "es",
        max_duration=3, max_chars=84, translation_unit_max_seconds=6,
    ))
    results = flatten(batches)

    assert " ".join(item.original_text for item in results) == " ".join(
        f"word{i}" for i in range(8)
    )
    assert all(item.translation_method.startswith("deterministic_timing") for item in results)
    assert all(not item.used_fallback for item in results)
    assert batches[-1][1] == 8


def test_deterministic_boundaries_respect_speaker_changes_and_pauses():
    words = [
        TranscriptWord("Hello", 0, .4, "A", .9),
        TranscriptWord("there", .5, .9, "A", .8),
        TranscriptWord("Friend", 2, 2.4, "B", .7),
    ]
    results = flatten(list(iter_deterministic_translation(
        words, Translator(), "en", "es", pause_seconds=.65,
    )))

    assert [item.original_text for item in results] == ["Hello there", "Friend"]
    assert [item.speaker_label for item in results] == ["A", "B"]


def test_confidence_is_averaged_without_changing_source_words():
    results = flatten(list(iter_deterministic_translation(
        timed_words(2), Translator(), "en", "es",
    )))

    assert results[0].original_text == "word0 word1"
    assert results[0].transcription_confidence == 0.895


def test_oversized_translation_resegments_and_retranslates():
    class ExpandingTranslator(Translator):
        def translate(self, text, source, target):
            self.calls.append((text, source, target))
            return "x" * (20 * len(text.split()))

    translator = ExpandingTranslator()
    results = flatten(list(iter_deterministic_translation(
        timed_words(8), translator, "en", "es",
        max_duration=10, max_chars=60,
    )))

    assert len(results) == 4
    assert all(item.translation_method == "deterministic_timing_resized" for item in results)
    assert all(len(item.translated_text) <= 60 for item in results)
    assert len(translator.calls) > len(results)


def test_identity_translation_preserves_same_language_text():
    class Identity:
        def translate(self, text, source, target):
            return text

    results = flatten(list(iter_deterministic_translation(
        timed_words(2), Identity(), "en", "en",
    )))

    assert results[0].translated_text == "word0 word1"


def test_neighboring_semantic_units_are_context_not_timing_instructions():
    class ContextTranslator:
        def __init__(self):
            self.calls = []

        def translate_with_context(
            self, text, source, target, context_before=(), context_after=(),
        ):
            from app.providers.local_translation import TranslationOutput
            self.calls.append((text, context_before, context_after))
            return TranslationOutput(f"T:{text}", "context-test")

    words = [
        TranscriptWord("First.", 0, .4, "A", .9),
        TranscriptWord("Second.", 1, 1.4, "A", .9),
        TranscriptWord("Third.", 2, 2.4, "A", .9),
    ]
    translator = ContextTranslator()
    results = flatten(list(iter_deterministic_translation(
        words, translator, "en", "es",
        max_duration=.6, translation_unit_max_seconds=.5, context_captions=1,
    )))

    assert translator.calls[0] == ("First.", (), ("Second.",))
    assert translator.calls[1] == ("Second.", ("First.",), ("Third.",))
    assert [(item.start_time, item.end_time) for item in results] == [
        (0.0, .4), (1.0, 1.4), (2.0, 2.4),
    ]
