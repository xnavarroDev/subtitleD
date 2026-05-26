from pathlib import Path
from uuid import uuid4

from werkzeug.utils import secure_filename

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}


def ensure_storage_dirs(storage_dir):
    """Create the local storage folders used by upload and render workflows."""
    base = Path(storage_dir)
    for folder in ("uploads", "audio", "exports", "renders", "models"):
        (base / folder).mkdir(parents=True, exist_ok=True)


def is_allowed_video(filename):
    """Return whether a filename uses an MVP-supported video extension."""
    return Path(filename or "").suffix.lower() in ALLOWED_VIDEO_EXTENSIONS


def save_video_upload(file_storage, upload_dir):
    """Validate and persist an uploaded video using a collision-resistant name."""
    original_name = secure_filename(file_storage.filename or "")
    if not original_name or not is_allowed_video(original_name):
        allowed = ", ".join(sorted(ALLOWED_VIDEO_EXTENSIONS))
        raise ValueError(f"Unsupported video type. Allowed extensions: {allowed}")

    extension = Path(original_name).suffix.lower()
    path = Path(upload_dir) / f"{uuid4().hex}{extension}"
    path.parent.mkdir(parents=True, exist_ok=True)
    file_storage.save(path)
    return path
