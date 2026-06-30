from app.providers.contextual_translation import ContextCaption
from app.providers.transcription import TranscriptWord
from app.utils.contextual_translation import iter_contextual_translation


def timed_words(count=12):
    return [
        TranscriptWord(f"word{i}", float(i), float(i) + 0.5, "A", 0.9 - i * 0.01)
        for i in range(count)
    ]


class WindowTranslator:
    def __init__(self):
        self.calls = []

    def translate_window(self, words, previous, source, target):
        self.calls.append((tuple(word.id for word in words), tuple(previous)))
        return [
            ContextCaption(word.id, word.id, f"T:{word.text}")
            for word in words
        ]


class FallbackTranslator:
    def translate(self, text, source, target):
        return f"F:{text}"


def test_sliding_window_commits_each_word_once_and_carries_context():
    provider = WindowTranslator()
    batches = list(iter_contextual_translation(
        timed_words(), provider, FallbackTranslator(), "en", "es",
        window_seconds=6, lookahead_seconds=2, context_caption_count=2,
        max_duration=6, max_chars=84,
    ))
    results = [caption for batch, _cursor, _warning in batches for caption in batch]

    assert [item.start_index for item in results] == list(range(12))
    assert [item.original_text for item in results] == [f"word{i}" for i in range(12)]
    assert len(provider.calls) > 1
    assert provider.calls[1][0][0] == "w000004"
    assert provider.calls[1][1][-1]["translation"] == "T:word3"


def test_failure_retries_smaller_window_then_uses_deterministic_fallback():
    class Broken:
        def __init__(self):
            self.calls = 0

        def translate_window(self, *args):
            self.calls += 1
            raise RuntimeError("bad json")

    broken = Broken()
    batches = list(iter_contextual_translation(
        timed_words(5), broken, FallbackTranslator(), "en", "es",
        window_seconds=10, lookahead_seconds=2, max_duration=3, max_chars=84,
    ))
    results = [caption for batch, _cursor, _warning in batches for caption in batch]

    assert broken.calls == 2
    assert all(item.used_fallback for item in results)
    assert batches[0][2] and "fallback used" in batches[0][2]
    assert " ".join(item.original_text for item in results) == "word0 word1 word2 word3 word4"


def test_retry_window_is_actually_smaller_than_the_initial_window():
    class FailOnce:
        def __init__(self):
            self.window_sizes = []

        def translate_window(self, words, *args):
            self.window_sizes.append(len(words))
            if len(self.window_sizes) == 1:
                raise RuntimeError("caption was too long")
            return [ContextCaption(word.id, word.id, f"T:{word.text}") for word in words]

    provider = FailOnce()
    next(iter_contextual_translation(
        timed_words(20), provider, FallbackTranslator(), "en", "es",
        window_seconds=12, lookahead_seconds=3, max_duration=6, max_chars=84,
    ))

    assert provider.window_sizes == [12, 5]


def test_confidence_is_averaged_without_changing_raw_source_words():
    provider = WindowTranslator()
    batch, completed, warning = next(iter_contextual_translation(
        timed_words(2), provider, FallbackTranslator(), "en", "es",
        window_seconds=10, lookahead_seconds=0, max_duration=6, max_chars=84,
    ))

    assert completed == 2
    assert warning is None
    assert batch[0].original_text == "word0"
    assert batch[0].transcription_confidence == 0.9
