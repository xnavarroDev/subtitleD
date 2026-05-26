from app.utils.files import is_allowed_video


def test_is_allowed_video_accepts_expected_mvp_formats():
    assert is_allowed_video("clip.mp4")
    assert is_allowed_video("clip.MOV")
    assert is_allowed_video("clip.webm")
    assert is_allowed_video("clip.mkv")


def test_is_allowed_video_rejects_other_files():
    assert not is_allowed_video("notes.txt")
    assert not is_allowed_video("archive.zip")
