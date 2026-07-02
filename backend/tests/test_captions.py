from app.providers.transcription import TranscriptSegment, TranscriptWord
from app.utils.captions import (
    fit_translated_caption,
    flatten_transcript_words,
    segment_transcript,
    wrap_caption_text,
)


def test_segments_long_transcript_at_punctuation_and_duration():
    words = (
        TranscriptWord("This", 0, 1), TranscriptWord("ends.", 1, 2),
        TranscriptWord("Another", 2, 4), TranscriptWord("sentence", 4, 7),
    )
    result = segment_transcript([TranscriptSegment(0, 7, "This ends. Another sentence", words=words)])
    assert [item.text for item in result] == ["This ends.", "Another sentence"]
    assert all(item.end_time - item.start_time <= 6 for item in result)


def test_translation_expansion_is_refit_and_srt_text_wraps():
    segment = TranscriptSegment(0, 8, "Short source")
    result = fit_translated_caption(segment, " ".join(["translated"] * 12), 30)
    assert len(result) > 1
    assert all(len(item.translated_text) <= 30 for item in result)
    assert len(wrap_caption_text("A readable subtitle split across two balanced lines", 30).splitlines()) == 2


def test_unaligned_japanese_uses_estimated_character_timing():
    segment = TranscriptSegment(2, 4, "\u65e5\u672c\u8a9e", timing_quality="estimated")

    words = flatten_transcript_words([segment])

    assert [word.text for word in words] == ["\u65e5", "\u672c", "\u8a9e"]
    assert all(word.timing_quality == "estimated" for word in words)
    assert words[0].start_time == 2
    assert words[-1].end_time == 4


def test_estimated_timing_quality_survives_caption_segmentation():
    segment = TranscriptSegment(0, 1, "\u65e5\u672c\u8a9e\u3002", timing_quality="estimated")

    captions = segment_transcript([segment])

    assert captions[0].timing_quality == "estimated"
    assert captions[0].text == "\u65e5\u672c\u8a9e\u3002"
