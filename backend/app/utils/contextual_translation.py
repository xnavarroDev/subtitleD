from dataclasses import dataclass

from ..providers.contextual_translation import ContextWord
from .captions import normalize_caption_text


@dataclass(frozen=True)
class TranslationResult:
    start_index: int
    end_index: int
    start_time: float
    end_time: float
    original_text: str
    translated_text: str
    speaker_label: str | None
    transcription_confidence: float | None
    used_fallback: bool = False

    @property
    def word_count(self):
        return self.end_index - self.start_index + 1


def index_words(words):
    return [
        ContextWord(
            id=f"w{index:06d}",
            text=word.text,
            start_time=float(word.start_time),
            end_time=float(word.end_time),
            speaker_label=word.speaker_label,
            confidence=word.confidence,
        )
        for index, word in enumerate(words)
    ]


def iter_contextual_translation(
    words,
    contextual_provider,
    fallback_provider,
    source_language,
    target_language,
    window_seconds=20,
    lookahead_seconds=4,
    context_caption_count=2,
    max_duration=6,
    max_chars=84,
):
    """Yield committed caption batches while retaining trailing words as lookahead."""
    indexed = index_words(words)
    id_to_index = {word.id: index for index, word in enumerate(indexed)}
    cursor = 0
    committed = []
    while cursor < len(indexed):
        window_end = _end_index_for_seconds(indexed, cursor, window_seconds)
        window = indexed[cursor:window_end + 1]
        previous = [
            {"source": item.original_text, "translation": item.translated_text}
            for item in committed[-max(int(context_caption_count), 0):]
        ]
        warning = None
        try:
            proposed = contextual_provider.translate_window(
                window, previous, source_language, target_language
            )
            candidates = _to_results(proposed, indexed, id_to_index)
        except Exception as first_error:
            retry_seconds = max(
                1.0,
                min(float(window_seconds) / 2, float(max_duration) * 0.75),
            )
            smaller_end = _end_index_for_seconds(indexed, cursor, retry_seconds)
            smaller = indexed[cursor:smaller_end + 1]
            try:
                proposed = contextual_provider.translate_window(
                    smaller, previous, source_language, target_language
                )
                candidates = _to_results(proposed, indexed, id_to_index)
                window_end = smaller_end
                window = smaller
            except Exception as second_error:
                fallback_end = _end_index_for_seconds(
                    indexed,
                    cursor,
                    max(float(window_seconds) - float(lookahead_seconds), float(max_duration)),
                )
                candidates = _fallback_results(
                    indexed,
                    cursor,
                    fallback_end,
                    fallback_provider,
                    source_language,
                    target_language,
                    max_duration,
                    max_chars,
                )
                warning = (
                    f"Contextual translation fallback used near {indexed[cursor].start_time:.1f}s: "
                    f"{second_error or first_error}"
                )
                window_end = fallback_end
                window = indexed[cursor:fallback_end + 1]

        final_window = window_end == len(indexed) - 1
        if final_window or warning:
            commit_count = len(candidates)
        else:
            cutoff = window[-1].end_time - float(lookahead_seconds)
            commit_count = sum(item.end_time <= cutoff for item in candidates)
            commit_count = max(commit_count, 1)
        batch = candidates[:commit_count]
        if not batch or batch[0].start_index != cursor:
            raise RuntimeError("Contextual translation did not advance from the expected word.")
        cursor = batch[-1].end_index + 1
        committed.extend(batch)
        yield batch, cursor, warning


def _to_results(captions, all_words, id_to_index):
    results = []
    for caption in captions:
        start, end = id_to_index[caption.start_word_id], id_to_index[caption.end_word_id]
        results.append(_result_from_span(all_words, start, end, caption.translated_text, False))
    return results


def _fallback_results(words, start, end, provider, source_language, target_language, max_duration, max_chars):
    results = []
    cursor = start
    while cursor <= end:
        chunk_end = cursor
        while chunk_end + 1 <= end:
            candidate = words[cursor:chunk_end + 2]
            source_text = _join(candidate)
            speakers = {word.speaker_label for word in candidate if word.speaker_label}
            duration = candidate[-1].end_time - candidate[0].start_time
            if len(speakers) > 1 or duration > max_duration or len(source_text) > 60:
                break
            chunk_end += 1
        results.extend(_translate_fallback_span(words, cursor, chunk_end, provider, source_language, target_language, max_chars))
        cursor = chunk_end + 1
    return results


def _translate_fallback_span(words, start, end, provider, source_language, target_language, max_chars):
    source = _join(words[start:end + 1])
    translated = provider.translate(source, source_language, target_language)
    if len(normalize_caption_text(translated)) <= max_chars or start == end:
        return [_result_from_span(words, start, end, normalize_caption_text(translated), True)]
    midpoint = (start + end) // 2
    return _translate_fallback_span(words, start, midpoint, provider, source_language, target_language, max_chars) + _translate_fallback_span(words, midpoint + 1, end, provider, source_language, target_language, max_chars)


def _result_from_span(words, start, end, translated_text, used_fallback):
    span = words[start:end + 1]
    confidences = [word.confidence for word in span if word.confidence is not None]
    speakers = [word.speaker_label for word in span if word.speaker_label]
    return TranslationResult(
        start_index=start,
        end_index=end,
        start_time=span[0].start_time,
        end_time=span[-1].end_time,
        original_text=_join(span),
        translated_text=normalize_caption_text(translated_text),
        speaker_label=max(set(speakers), key=speakers.count) if speakers else None,
        transcription_confidence=(sum(confidences) / len(confidences)) if confidences else None,
        used_fallback=used_fallback,
    )


def _end_index_for_seconds(words, start, seconds):
    limit = words[start].start_time + float(seconds)
    end = start
    while end + 1 < len(words) and words[end + 1].end_time <= limit:
        end += 1
    return end


def _join(words):
    return normalize_caption_text(" ".join(word.text for word in words))
