import re
from dataclasses import dataclass

from ..providers.transcription import TranscriptSegment, TranscriptWord


_ENDING = re.compile(r"[.!?;:][\"')\]]*$")
_NO_SPACE_BEFORE = re.compile(r"\s+([,.;:!?%)}\]])")
_NO_SPACE_AFTER = re.compile(r"([({\[])\s+")


@dataclass(frozen=True)
class PreparedCaption:
    start_time: float
    end_time: float
    original_text: str
    translated_text: str
    speaker_label: str | None = None


def normalize_caption_text(text):
    value = " ".join(str(text or "").replace("\n", " ").split())
    return _NO_SPACE_AFTER.sub(r"\1", _NO_SPACE_BEFORE.sub(r"\1", value)).strip()


def segment_transcript(segments, max_duration=6, max_chars=84, pause_seconds=0.65):
    output = []
    for segment in segments:
        words = _timed_words(segment)
        for group in _required_groups(words, pause_seconds):
            output.extend(_split_group(group, max_duration, max_chars, pause_seconds))
    return output


def flatten_transcript_words(segments):
    """Return one ordered timed word stream without changing recognized text."""
    return [word for segment in segments for word in _timed_words(segment)]


def segment_words(words, max_duration=6, max_chars=84, pause_seconds=0.65):
    """Deterministically caption an aligned word range for provider fallback."""
    output = []
    for group in _required_groups(words, pause_seconds):
        output.extend(_split_group(group, max_duration, max_chars, pause_seconds))
    return output


def fit_translated_caption(segment, translated_text, max_chars=84):
    chunks = split_text(translated_text, max_chars)
    if len(chunks) == 1:
        return [PreparedCaption(segment.start_time, segment.end_time, segment.text, chunks[0], segment.speaker_label)]
    originals = _split_into_count(segment.text, len(chunks))
    weights = [max(len(value), 1) for value in chunks]
    duration = max(segment.end_time - segment.start_time, 0.001)
    cursor = segment.start_time
    output = []
    for index, value in enumerate(chunks):
        end = segment.end_time if index == len(chunks) - 1 else cursor + duration * weights[index] / sum(weights)
        output.append(PreparedCaption(cursor, max(end, cursor + 0.001), originals[index], value, segment.speaker_label))
        cursor = end
    return output


def split_text(text, max_chars=84):
    tokens = []
    for token in normalize_caption_text(text).split():
        tokens.extend(token[i:i + max_chars] for i in range(0, len(token), max_chars))
    chunks, current = [], []
    for token in tokens:
        candidate = normalize_caption_text(" ".join([*current, token]))
        if current and len(candidate) > max_chars:
            chunks.append(normalize_caption_text(" ".join(current)))
            current = [token]
        else:
            current.append(token)
    if current:
        chunks.append(normalize_caption_text(" ".join(current)))
    return chunks or [""]


def wrap_caption_text(text, line_chars=42):
    value = normalize_caption_text(text)
    if len(value) <= line_chars:
        return value
    words = value.split()
    choices = []
    for i in range(1, len(words)):
        left, right = " ".join(words[:i]), " ".join(words[i:])
        choices.append((max(len(left), len(right)), abs(len(left) - len(right)), left, right))
    valid = [item for item in choices if len(item[2]) <= line_chars and len(item[3]) <= line_chars]
    if not choices:
        return value
    _, _, left, right = min(valid or choices)
    return f"{left}\n{right}"


def _timed_words(segment):
    raw = [word for word in (segment.words or ()) if word.text.strip()]
    if raw and all(word.start_time is not None and word.end_time is not None for word in raw):
        return [TranscriptWord(word.text, float(word.start_time), float(word.end_time), word.speaker_label or segment.speaker_label, word.confidence) for word in raw]
    tokens = [word.text for word in raw] if raw else str(segment.text).split()
    speakers = [word.speaker_label or segment.speaker_label for word in raw] if raw else [segment.speaker_label] * len(tokens)
    weights = [max(len(token), 1) for token in tokens]
    total, duration, cursor = sum(weights), max(segment.end_time - segment.start_time, 0.001), segment.start_time
    output = []
    for index, (token, speaker, weight) in enumerate(zip(tokens, speakers, weights)):
        end = segment.end_time if index == len(tokens) - 1 else cursor + duration * weight / total
        output.append(TranscriptWord(token, cursor, max(end, cursor + 0.001), speaker))
        cursor = end
    return output


def _required_groups(words, pause_seconds):
    groups, current = [], []
    for word in words:
        if current:
            previous = current[-1]
            changed = previous.speaker_label and word.speaker_label and previous.speaker_label != word.speaker_label
            paused = word.start_time - previous.end_time >= pause_seconds
            if changed or paused:
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def _split_group(words, max_duration, max_chars, pause_seconds):
    output, start = [], 0
    while start < len(words):
        end, preferred = start, None
        while end < len(words):
            candidate = words[start:end + 1]
            text = _join(candidate)
            duration = candidate[-1].end_time - candidate[0].start_time
            if end > start and (len(text) > max_chars or duration > max_duration):
                break
            if _ENDING.search(words[end].text) or (end + 1 < len(words) and words[end + 1].start_time - words[end].end_time >= pause_seconds * 0.65):
                preferred = end + 1
            end += 1
        split_at = end if end == len(words) else (preferred or max(end, start + 1))
        chunk = words[start:split_at]
        if len(chunk) == 1 and len(_join(chunk)) > max_chars:
            pieces = split_text(chunk[0].text, max_chars)
            piece_duration = (chunk[0].end_time - chunk[0].start_time) / len(pieces)
            for i, piece in enumerate(pieces):
                piece_start = chunk[0].start_time + i * piece_duration
                output.append(TranscriptSegment(piece_start, chunk[0].end_time if i == len(pieces)-1 else piece_start + piece_duration, piece, chunk[0].speaker_label))
        else:
            output.append(TranscriptSegment(chunk[0].start_time, chunk[-1].end_time, _join(chunk), _speaker(chunk), tuple(chunk)))
        start = split_at
    return output


def _join(words):
    return normalize_caption_text(" ".join(word.text.strip() for word in words))


def _speaker(words):
    counts = {}
    for word in words:
        if word.speaker_label:
            counts[word.speaker_label] = counts.get(word.speaker_label, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _split_into_count(text, count):
    words = str(text or "").split()
    return [normalize_caption_text(" ".join(words[round(i*len(words)/count):round((i+1)*len(words)/count)])) for i in range(count)]
