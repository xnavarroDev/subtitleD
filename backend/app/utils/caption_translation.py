import re
from dataclasses import dataclass

from .captions import normalize_caption_text


_ENDING = re.compile(r"[.!?;:。！？；：][\"')\]」』）】]*$")


@dataclass(frozen=True)
class _IndexedWord:
    id: str
    text: str
    start_time: float
    end_time: float
    speaker_label: str | None = None
    confidence: float | None = None
    timing_quality: str = "forced_aligned"
    reconstruction_method: str = "raw"
    source_was_reconstructed: bool = False


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
    translation_method: str = "deterministic_timing"
    timing_quality: str = "forced_aligned"
    translation_provider: str = "unknown"
    translation_model: str | None = None
    source_reconstruction_method: str = "raw"
    source_was_reconstructed: bool = False
    translation_unit_id: str | None = None
    translation_confidence_warning: str | None = None
    warning: str | None = None

    @property
    def word_count(self):
        return self.end_index - self.start_index + 1


@dataclass(frozen=True)
class _Boundary:
    start_index: int
    end_index: int
    used_fallback: bool = False
    method: str = "deterministic_timing"


def index_words(words):
    return [
        _IndexedWord(
            id=f"w{index:06d}",
            text=word.text,
            start_time=float(word.start_time),
            end_time=float(word.end_time),
            speaker_label=word.speaker_label,
            confidence=word.confidence,
            timing_quality=word.timing_quality,
            reconstruction_method=getattr(word, "reconstruction_method", "raw"),
            source_was_reconstructed=getattr(word, "source_was_reconstructed", False),
        )
        for index, word in enumerate(words)
    ]


def iter_deterministic_translation(
    words,
    translation_provider,
    source_language,
    target_language,
    max_duration=6,
    max_chars=84,
    pause_seconds=0.65,
    review_confidence_threshold=0.45,
    translation_unit_max_seconds=12,
):
    """Choose deterministic boundaries and translate semantic source units."""
    indexed = index_words(words)
    if not indexed:
        return
    boundaries = _deterministic_boundaries(
        indexed, 0, len(indexed) - 1, max_duration, max_chars, pause_seconds
    )
    for group in _group_boundaries(
        boundaries, indexed, translation_unit_max_seconds
    ):
        batch = []
        batch.extend(_translate_boundary_group(
            indexed,
            group,
            translation_provider,
            source_language,
            target_language,
            max_chars,
            review_confidence_threshold,
        ))
        translation_warnings = list(dict.fromkeys(
            item.warning for item in batch if item.warning
        ))
        warning = " ".join(translation_warnings) if translation_warnings else None
        yield batch, group[-1].end_index + 1, warning


def _group_boundaries(boundaries, words, max_seconds):
    groups = []
    current = []
    for boundary in boundaries:
        if current:
            first = current[0]
            previous = current[-1]
            combined_duration = (
                words[boundary.end_index].end_time
                - words[first.start_index].start_time
            )
            previous_span = words[previous.start_index:previous.end_index + 1]
            previous_speakers = {
                word.speaker_label for word in previous_span if word.speaker_label
            }
            next_speakers = {
                word.speaker_label
                for word in words[boundary.start_index:boundary.end_index + 1]
                if word.speaker_label
            }
            should_break = (
                combined_duration > float(max_seconds)
                or previous_speakers != next_speakers
                or previous.used_fallback != boundary.used_fallback
                or bool(_ENDING.search(words[previous.end_index].text))
            )
            if should_break:
                groups.append(current)
                current = []
        current.append(boundary)
    if current:
        groups.append(current)
    return groups


def _translate_boundary_group(
    words,
    boundaries,
    provider,
    source_language,
    target_language,
    max_chars,
    review_confidence_threshold,
):
    first, last = boundaries[0], boundaries[-1]
    unit_id = f"u{first.start_index:06d}-{last.end_index:06d}"
    if len(boundaries) == 1:
        return _translate_boundary(
            words, first.start_index, first.end_index, provider,
            source_language, target_language, max_chars,
            first.used_fallback, first.method,
            review_confidence_threshold, unit_id,
        )

    source = _join(words[first.start_index:last.end_index + 1])
    translated, provider_name, model_name, provider_warning = _provider_translate(
        provider, source, source_language, target_language
    )
    token_count = len(translated.split()) if len(translated.split()) > 1 else len(translated)
    if (
        len(translated) > len(boundaries) * int(max_chars)
        or token_count < len(boundaries)
    ):
        output = []
        for boundary in boundaries:
            output.extend(_translate_boundary(
                words, boundary.start_index, boundary.end_index, provider,
                source_language, target_language, max_chars,
                boundary.used_fallback, f"{boundary.method}_resized",
                review_confidence_threshold, unit_id,
            ))
        return output

    chunks = _split_target_into_count(translated, boundaries, words)
    if any(not chunk or len(chunk) > int(max_chars) for chunk in chunks):
        output = []
        for boundary in boundaries:
            output.extend(_translate_boundary(
                words, boundary.start_index, boundary.end_index, provider,
                source_language, target_language, max_chars,
                boundary.used_fallback, f"{boundary.method}_resized",
                review_confidence_threshold, unit_id,
            ))
        return output
    output = []
    for boundary, chunk in zip(boundaries, chunks):
        output.append(_result_from_span(
            words,
            boundary.start_index,
            boundary.end_index,
            chunk,
            boundary.used_fallback,
            f"{boundary.method}_unit",
            provider_name,
            model_name,
            provider_warning,
            review_confidence_threshold,
            unit_id,
        ))
    return output


def _split_target_into_count(text, boundaries, words):
    whitespace_tokens = text.split()
    tokens = whitespace_tokens if len(whitespace_tokens) > 1 else list(text)
    weights = [
        max(len(_join(words[item.start_index:item.end_index + 1])), 1)
        for item in boundaries
    ]
    total_weight = sum(weights)
    chunks = []
    previous = 0
    cumulative = 0
    for index, weight in enumerate(weights):
        cumulative += weight
        end = len(tokens) if index == len(weights) - 1 else round(
            len(tokens) * cumulative / total_weight
        )
        end = max(end, previous + 1) if previous < len(tokens) else previous
        chunk_tokens = tokens[previous:end]
        separator = " " if len(whitespace_tokens) > 1 else ""
        chunks.append(normalize_caption_text(separator.join(chunk_tokens)))
        previous = end
    return chunks


def _deterministic_boundaries(
    words, start, end, max_duration, max_chars, pause_seconds,
):
    output = []
    cursor = start
    while cursor <= end:
        candidate_end = cursor
        last_fit = cursor
        preferred = None
        while candidate_end <= end:
            span = words[cursor:candidate_end + 1]
            speakers = {word.speaker_label for word in span if word.speaker_label}
            duration = span[-1].end_time - span[0].start_time
            oversized = duration > float(max_duration) or len(_join(span)) > int(max_chars)
            if candidate_end > cursor and (len(speakers) > 1 or oversized):
                break
            last_fit = candidate_end
            next_word = words[candidate_end + 1] if candidate_end < end else None
            paused = (
                next_word is not None
                and next_word.start_time - words[candidate_end].end_time
                >= float(pause_seconds)
            )
            changes_speaker = (
                next_word is not None
                and words[candidate_end].speaker_label
                and next_word.speaker_label
                and words[candidate_end].speaker_label != next_word.speaker_label
            )
            if _ENDING.search(words[candidate_end].text) or paused or changes_speaker:
                preferred = candidate_end
            candidate_end += 1
        split_end = preferred if preferred is not None else last_fit
        output.append(_Boundary(
            cursor, split_end, False, "deterministic_timing"
        ))
        cursor = split_end + 1
    return output


def _translate_boundary(
    words,
    start,
    end,
    provider,
    source_language,
    target_language,
    max_chars,
    used_fallback,
    method,
    review_confidence_threshold,
    translation_unit_id,
):
    source = _join(words[start:end + 1])
    translated, provider_name, model_name, provider_warning = _provider_translate(
        provider, source, source_language, target_language
    )
    if not translated:
        raise RuntimeError("Translation provider returned empty caption text.")
    if len(translated) <= int(max_chars) or start == end:
        return [
            _result_from_span(
                words, start, end, translated, used_fallback, method,
                provider_name, model_name, provider_warning,
                review_confidence_threshold, translation_unit_id,
            )
        ]

    split_at = _best_split_index(words, start, end)
    resized_method = "deterministic_timing_resized"
    return _translate_boundary(
        words, start, split_at, provider, source_language, target_language,
        max_chars, used_fallback, resized_method, review_confidence_threshold,
        translation_unit_id,
    ) + _translate_boundary(
        words, split_at + 1, end, provider, source_language, target_language,
        max_chars, used_fallback, resized_method, review_confidence_threshold,
        translation_unit_id,
    )


def _provider_translate(provider, source, source_language, target_language):
    if hasattr(provider, "translate_with_metadata"):
        output = provider.translate_with_metadata(source, source_language, target_language)
        translated_value = output.text
        provider_name = output.provider
        model_name = output.model
        provider_warning = output.warning
    else:
        translated_value = provider.translate(source, source_language, target_language)
        provider_name = getattr(
            provider, "provider_name", provider.__class__.__name__.casefold()
        )
        model_name = None
        provider_warning = None
    translated = normalize_caption_text(translated_value)
    if not translated:
        raise RuntimeError("Translation provider returned empty caption text.")
    return translated, provider_name, model_name, provider_warning


def _best_split_index(words, start, end):
    midpoint = (start + end - 1) / 2
    choices = []
    for index in range(start, end):
        left = words[index]
        right = words[index + 1]
        pause = max(right.start_time - left.end_time, 0)
        score = pause * 20 - abs(index - midpoint)
        if _ENDING.search(left.text):
            score += 100
        if left.speaker_label and right.speaker_label and left.speaker_label != right.speaker_label:
            score += 200
        choices.append((score, index))
    return max(choices)[1]


def _result_from_span(
    words, start, end, translated_text, used_fallback, translation_method,
    translation_provider="unknown", translation_model=None, warning=None,
    review_confidence_threshold=0.45, translation_unit_id=None,
):
    span = words[start:end + 1]
    confidences = [word.confidence for word in span if word.confidence is not None]
    speakers = [word.speaker_label for word in span if word.speaker_label]
    average_confidence = (
        sum(confidences) / len(confidences) if confidences else None
    )
    reconstructed = any(word.source_was_reconstructed for word in span)
    methods = sorted({
        word.reconstruction_method for word in span
        if word.reconstruction_method and word.reconstruction_method != "raw"
    })
    confidence_warning = None
    if average_confidence is not None and average_confidence < review_confidence_threshold:
        confidence_warning = (
            f"Low-confidence source ({average_confidence:.0%}); review the raw transcript."
        )
    return TranslationResult(
        start_index=start,
        end_index=end,
        start_time=span[0].start_time,
        end_time=span[-1].end_time,
        original_text=_join(span),
        translated_text=normalize_caption_text(translated_text),
        speaker_label=max(set(speakers), key=speakers.count) if speakers else None,
        transcription_confidence=average_confidence,
        used_fallback=used_fallback,
        translation_method=translation_method,
        timing_quality=(
            "estimated"
            if any(word.timing_quality == "estimated" for word in span)
            else "forced_aligned"
        ),
        translation_provider=translation_provider,
        translation_model=translation_model,
        source_reconstruction_method="+".join(methods) if methods else "raw",
        source_was_reconstructed=reconstructed,
        translation_unit_id=translation_unit_id,
        translation_confidence_warning=confidence_warning,
        warning=warning,
    )


def _join(words):
    return normalize_caption_text(" ".join(word.text for word in words))
