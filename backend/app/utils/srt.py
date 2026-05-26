from pathlib import Path
from uuid import uuid4


def format_srt_timestamp(seconds):
    """Convert seconds to the `HH:MM:SS,mmm` timestamp format required by SRT."""
    total_ms = int(round(max(float(seconds), 0) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _segment_value(segment, name):
    """Read a field from either a SQLAlchemy model or a dict-like test object."""
    if isinstance(segment, dict):
        return segment.get(name)
    return getattr(segment, name)


def segments_to_srt(segments):
    """Render ordered subtitle segments into SRT text."""
    blocks = []
    for index, segment in enumerate(segments, start=1):
        start_time = _segment_value(segment, "start_time")
        end_time = _segment_value(segment, "end_time")
        translated_text = _segment_value(segment, "translated_text") or ""
        original_text = _segment_value(segment, "original_text") or ""
        speaker_label = (_segment_value(segment, "speaker_label") or "").strip()
        text = translated_text.strip() or original_text.strip()
        if speaker_label:
            text = f"[{speaker_label}] {text}"
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_timestamp(start_time)} --> {format_srt_timestamp(end_time)}",
                    text,
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def generate_srt(project_id, output_path=None):
    """Generate an SRT file for a project from translated subtitle segments."""
    from flask import current_app

    from app.models import Project, SubtitleSegment

    project = Project.query.get(project_id)
    if not project:
        raise ValueError("Project not found")

    segments = (
        SubtitleSegment.query.filter_by(project_id=project_id)
        .order_by(SubtitleSegment.segment_index.asc())
        .all()
    )
    if not segments:
        raise ValueError("No subtitle segments to export")

    path = Path(output_path) if output_path else _default_srt_path(project.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(segments_to_srt(segments), encoding="utf-8")
    return path


def _default_srt_path(project_id):
    """Build a unique SRT export path for the project."""
    from flask import current_app

    storage_dir = Path(current_app.config["STORAGE_DIR"])
    return storage_dir / "exports" / f"{project_id}-{uuid4().hex}.srt"
