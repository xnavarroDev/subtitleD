"""Language-neutral repair of suspicious diarization fragments for translation."""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ReconstructionResult:
    words: tuple
    changed_word_count: int = 0
    warning: str | None = None


def reconstruct_source_words(
    words,
    enabled=True,
    max_gap_seconds=0.2,
    max_fragment_chars=2,
    low_confidence_threshold=0.45,
):
    """Return an effective word stream without mutating raw recognition records.

    Short speaker runs can be alignment artifacts when they directly touch a
    longer, low-confidence run. In that narrow case, use the larger run's
    speaker for boundary selection while preserving every recognized character.
    """
    values = list(words)
    if not enabled or len(values) < 2:
        return ReconstructionResult(tuple(values))

    runs = _speaker_runs(values)
    replacements = {}
    for run_index, run in enumerate(runs):
        run_start, run_end, run_speaker = run
        if not run_speaker or _character_count(values, run_start, run_end) > max_fragment_chars:
            continue
        candidates = []
        if run_index > 0:
            candidates.append(runs[run_index - 1])
        if run_index + 1 < len(runs):
            candidates.append(runs[run_index + 1])
        candidates = [
            candidate for candidate in candidates
            if _can_attach(
                values, run, candidate, max_gap_seconds,
                max_fragment_chars, low_confidence_threshold,
            )
        ]
        if not candidates:
            continue
        target = max(
            candidates,
            key=lambda item: _character_count(values, item[0], item[1]),
        )
        for index in range(run_start, run_end + 1):
            replacements[index] = target[2]

    output = []
    for index, word in enumerate(values):
        speaker = replacements.get(index)
        if speaker and speaker != word.speaker_label:
            output.append(replace(
                word,
                speaker_label=speaker,
                reconstruction_method="speaker_fragment_merge",
                source_was_reconstructed=True,
            ))
        else:
            output.append(word)
    changed = len(replacements)
    warning = None
    if changed:
        warning = (
            f"Source reconstruction reassigned {changed} short diarization "
            "fragment(s) for translation; raw WhisperX words were preserved."
        )
    return ReconstructionResult(tuple(output), changed, warning)


def _speaker_runs(words):
    runs = []
    start = 0
    for index in range(1, len(words) + 1):
        if index == len(words) or words[index].speaker_label != words[start].speaker_label:
            runs.append((start, index - 1, words[start].speaker_label))
            start = index
    return runs


def _can_attach(
    words, fragment, candidate, max_gap_seconds,
    max_fragment_chars, low_confidence_threshold,
):
    frag_start, frag_end, frag_speaker = fragment
    other_start, other_end, other_speaker = candidate
    if not other_speaker or other_speaker == frag_speaker:
        return False
    if _character_count(words, other_start, other_end) <= max_fragment_chars * 2:
        return False
    confidences = [
        words[index].confidence for index in range(other_start, other_end + 1)
        if words[index].confidence is not None
    ]
    average = sum(confidences) / len(confidences) if confidences else None
    if average is None or average > low_confidence_threshold:
        return False
    if other_end < frag_start:
        gap = words[frag_start].start_time - words[other_end].end_time
    else:
        gap = words[other_start].start_time - words[frag_end].end_time
    return gap <= max_gap_seconds


def _character_count(words, start, end):
    return sum(len(str(words[index].text).strip()) for index in range(start, end + 1))
