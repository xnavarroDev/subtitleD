from app.providers.transcription import TranscriptSegment, TranscriptWord
from app.utils.captions import fit_translated_caption, segment_transcript, wrap_caption_text


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
