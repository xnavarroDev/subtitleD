from app.utils.srt import format_srt_timestamp, segments_to_srt


def test_format_srt_timestamp_rounds_and_pads():
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(61.234) == "00:01:01,234"
    assert format_srt_timestamp(3661.2) == "01:01:01,200"


def test_segments_to_srt_prefers_translated_text():
    segments = [
        {
            "start_time": 0,
            "end_time": 2.5,
            "original_text": "Hello",
            "translated_text": "Hola",
        },
        {
            "start_time": 3,
            "end_time": 4,
            "original_text": "Fallback",
            "translated_text": "",
        },
    ]

    assert segments_to_srt(segments) == (
        "1\n"
        "00:00:00,000 --> 00:00:02,500\n"
        "Hola\n\n"
        "2\n"
        "00:00:03,000 --> 00:00:04,000\n"
        "Fallback\n"
    )


def test_segments_to_srt_prefixes_speaker_label():
    segments = [
        {
            "start_time": 0,
            "end_time": 2,
            "original_text": "Hello",
            "translated_text": "Hola",
            "speaker_label": "SPEAKER_00",
        }
    ]

    assert segments_to_srt(segments) == (
        "1\n"
        "00:00:00,000 --> 00:00:02,000\n"
        "[SPEAKER_00] Hola\n"
    )
