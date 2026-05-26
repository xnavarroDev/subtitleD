from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from .extensions import db
from .models import Project, ProjectStatus, SubtitleSegment
from .utils.files import save_video_upload
from .utils.srt import generate_srt

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.errorhandler(HTTPException)
def handle_http_error(exc):
    """Return framework-raised HTTP errors as JSON for the React client."""
    return jsonify({"error": exc.description or exc.name}), exc.code


@api_bp.post("/projects")
def create_project():
    """Create a project record before video upload starts."""
    payload = request.get_json(silent=True) or {}
    missing = [
        key
        for key in ("title", "source_language", "target_language")
        if not payload.get(key)
    ]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    project = Project(
        title=payload["title"].strip(),
        source_language=payload["source_language"].strip(),
        target_language=payload["target_language"].strip(),
        min_speakers=_parse_optional_int(payload.get("min_speakers"), "min_speakers"),
        max_speakers=_parse_optional_int(payload.get("max_speakers"), "max_speakers"),
        status=ProjectStatus.CREATED,
    )
    if (
        project.min_speakers is not None
        and project.max_speakers is not None
        and project.min_speakers > project.max_speakers
    ):
        return jsonify({"error": "min_speakers cannot be greater than max_speakers"}), 400
    db.session.add(project)
    db.session.commit()
    return jsonify(project.to_dict()), 201


@api_bp.get("/projects")
def list_projects():
    """Return projects newest-first for the dashboard list."""
    projects = Project.query.order_by(Project.created_at.desc()).all()
    return jsonify([project.to_dict() for project in projects])


@api_bp.get("/projects/<project_id>")
def get_project(project_id):
    """Return project metadata and media/download URLs."""
    project = _project_or_404(project_id)
    return jsonify(project.to_dict())


@api_bp.post("/projects/<project_id>/video")
def upload_video(project_id):
    """Validate and attach an uploaded source video to a project."""
    project = _project_or_404(project_id)
    upload = request.files.get("video")
    if not upload or not upload.filename:
        return jsonify({"error": "Upload a video file with form field 'video'"}), 400

    try:
        path = save_video_upload(
            upload, Path(current_app.config["STORAGE_DIR"]) / "uploads"
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    project.source_video_path = str(path)
    project.status = ProjectStatus.UPLOADED
    project.error_message = None
    db.session.commit()
    return jsonify(project.to_dict())


@api_bp.post("/projects/<project_id>/process")
def process_project(project_id):
    """Queue background transcription and translation work."""
    project = _project_or_404(project_id)
    if not project.source_video_path:
        return jsonify({"error": "Upload a video before processing"}), 400

    from .tasks import process_video_task

    project.status = ProjectStatus.PROCESSING
    project.error_message = None
    db.session.commit()
    task = process_video_task.delay(project.id)
    return jsonify({"task_id": task.id, "project": project.to_dict()}), 202


@api_bp.get("/projects/<project_id>/segments")
def list_segments(project_id):
    """Return editable subtitle segments in playback order."""
    _project_or_404(project_id)
    segments = (
        SubtitleSegment.query.filter_by(project_id=project_id)
        .order_by(SubtitleSegment.segment_index.asc())
        .all()
    )
    return jsonify([segment.to_dict() for segment in segments])


@api_bp.patch("/segments/<segment_id>")
def update_segment(segment_id):
    """Update translated text or timing for a single subtitle segment."""
    segment = SubtitleSegment.query.get(segment_id)
    if not segment:
        abort(404, description="Subtitle segment not found")

    payload = request.get_json(silent=True) or {}
    if "translated_text" in payload:
        segment.translated_text = str(payload["translated_text"])
    if "speaker_label" in payload:
        value = payload["speaker_label"]
        segment.speaker_label = str(value).strip() or None if value is not None else None
    if "start_time" in payload:
        segment.start_time = _parse_time(payload["start_time"], "start_time")
    if "end_time" in payload:
        segment.end_time = _parse_time(payload["end_time"], "end_time")
    if segment.start_time >= segment.end_time:
        return jsonify({"error": "start_time must be less than end_time"}), 400

    db.session.commit()
    return jsonify(segment.to_dict())


@api_bp.post("/projects/<project_id>/export/srt")
def export_srt(project_id):
    """Generate and register an SRT export for the project."""
    project = _project_or_404(project_id)
    try:
        srt_path = generate_srt(project.id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    project.srt_path = str(srt_path)
    db.session.commit()
    return jsonify(
        {
            "srt_path": str(srt_path),
            "download_url": f"/api/projects/{project.id}/export/srt/download",
        }
    )


@api_bp.get("/projects/<project_id>/export/srt/download")
def download_srt(project_id):
    """Download the latest generated SRT export."""
    project = _project_or_404(project_id)
    return _send_existing_file(project.srt_path, as_attachment=True)


@api_bp.post("/projects/<project_id>/render")
def render_project(project_id):
    """Queue FFmpeg subtitle burn-in for a processed project."""
    project = _project_or_404(project_id)
    if not project.source_video_path:
        return jsonify({"error": "Upload a video before rendering"}), 400

    if not project.segments:
        return jsonify({"error": "Process the video before rendering"}), 400

    from .tasks import render_video_task

    project.status = ProjectStatus.RENDERING
    project.error_message = None
    db.session.commit()
    task = render_video_task.delay(project.id)
    return jsonify({"task_id": task.id, "project": project.to_dict()}), 202


@api_bp.get("/projects/<project_id>/download")
def download_render(project_id):
    """Download the rendered MP4 when FFmpeg output is available."""
    project = _project_or_404(project_id)
    return _send_existing_file(project.output_video_path, as_attachment=True)


@api_bp.get("/projects/<project_id>/status")
def project_status(project_id):
    """Return the lightweight polling payload used by the frontend."""
    project = _project_or_404(project_id)
    return jsonify(
        {
            "id": project.id,
            "status": project.status,
            "error_message": project.error_message,
            "updated_at": project.to_dict()["updated_at"],
        }
    )


@api_bp.get("/projects/<project_id>/media/source")
def source_media(project_id):
    """Stream the uploaded source video for browser preview."""
    project = _project_or_404(project_id)
    return _send_existing_file(project.source_video_path)


@api_bp.get("/projects/<project_id>/media/rendered")
def rendered_media(project_id):
    """Stream the rendered subtitled video for browser preview."""
    project = _project_or_404(project_id)
    return _send_existing_file(project.output_video_path)


def _project_or_404(project_id):
    """Fetch a project or raise a JSON-formatted 404."""
    project = Project.query.get(project_id)
    if not project:
        abort(404, description="Project not found")
    return project


def _parse_time(value, field_name):
    """Validate a non-negative numeric subtitle timestamp."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        abort(400, description=f"{field_name} must be a number")
    if parsed < 0:
        abort(400, description=f"{field_name} cannot be negative")
    return parsed


def _parse_optional_int(value, field_name):
    """Validate an optional positive integer request field."""
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        abort(400, description=f"{field_name} must be an integer")
    if parsed < 1:
        abort(400, description=f"{field_name} must be at least 1")
    return parsed


def _send_existing_file(path, as_attachment=False):
    """Send a file path only after confirming the artifact exists."""
    if not path or not Path(path).exists():
        abort(404, description="File not found")
    return send_file(path, as_attachment=as_attachment)
