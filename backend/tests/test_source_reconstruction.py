from app.providers.transcription import TranscriptWord
from app.utils.source_reconstruction import reconstruct_source_words


def test_short_speaker_fragments_attach_to_continuous_low_confidence_phrase():
    words = [
        TranscriptWord("ね", 0.0, 0.1, "A", 0.98),
        TranscriptWord("ぇ", 0.1, 0.2, "B", 0.2),
        TranscriptWord("斉", 0.2, 0.3, "B", 0.2),
        TranscriptWord("木", 0.3, 0.4, "B", 0.2),
        TranscriptWord("や", 0.4, 0.5, "B", 0.2),
        TranscriptWord("め", 0.5, 0.6, "B", 0.2),
        TranscriptWord("ろ", 0.6, 0.7, "A", 0.99),
    ]

    result = reconstruct_source_words(words)

    assert [word.speaker_label for word in result.words] == ["B"] * len(words)
    assert result.words[0].source_was_reconstructed is True
    assert result.words[-1].reconstruction_method == "speaker_fragment_merge"
    assert [word.speaker_label for word in words] == ["A", "B", "B", "B", "B", "B", "A"]
    assert "raw WhisperX words were preserved" in result.warning


def test_real_speaker_change_or_high_confidence_phrase_is_not_rewritten():
    words = [
        TranscriptWord("I", 0.0, 0.2, "A", 0.99),
        TranscriptWord("understand", 0.8, 1.2, "B", 0.95),
        TranscriptWord("you", 1.2, 1.4, "B", 0.94),
    ]

    result = reconstruct_source_words(words)

    assert result.changed_word_count == 0
    assert [word.speaker_label for word in result.words] == ["A", "B", "B"]
