from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from .diagnostics import PreflightError, require_job_preflight, run_system_diagnostics
from .extensions import db
from .models import Project, ProjectStatus, SubtitleSegment, TranscriptWordRecord
from .providers import get_translation_provider
from .providers.translation import (
    default_project_translation_provider,
    normalize_language as normalize_translation_language,
    normalize_project_translation_provider,
    translation_provider_options,
)
from .utils.files import save_video_upload
from .utils.srt import generate_srt

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.errorhandler(HTTPException)
def handle_http_error(exc):
    return jsonify({"error": exc.description or exc.name}), exc.code


@api_bp.post("/projects")
def create_project():
    payload = request.get_json(silent=True) or {}
    missing = [key for key in ("title", "source_language", "target_language") if not payload.get(key)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400
    project = Project(
        title=payload["title"].strip(),
        source_language=payload["source_language"].strip(),
        target_language=payload["target_language"].strip(),
        min_speakers=_parse_optional_int(payload.get("min_speakers"), "min_speakers"),
        max_speakers=_parse_optional_int(payload.get("max_speakers"), "max_speakers"),
        glossary=str(payload.get("glossary") or "").strip() or None,
        translation_provider=_parse_translation_provider(
            payload.get("translation_provider")
        ),
        detect_speakers=_parse_bool_value(payload.get("detect_speakers", False)),
        smooth_speaker_fragments=_parse_bool_value(
            payload.get("smooth_speaker_fragments", False)
        ),
        status=ProjectStatus.CREATED,
    )
    _apply_translation_settings(
        project,
        payload.get("translation_settings") or {},
        defaults=_translation_setting_defaults(),
    )
    if project.min_speakers is not None and project.max_speakers is not None and project.min_speakers > project.max_speakers:
        return jsonify({"error": "min_speakers cannot be greater than max_speakers"}), 400
    db.session.add(project)
    db.session.commit()
    return jsonify(project.to_dict()), 201


@api_bp.get("/projects")
def list_projects():
    names = _translation_language_names()
    return jsonify([project.to_dict(language_names=names) for project in Project.query.order_by(Project.created_at.desc()).all()])


@api_bp.get("/languages")
def list_languages():
    provider_name = None
    if "provider" in request.args:
        provider_name = _parse_translation_provider(request.args.get("provider"))
    try:
        return jsonify(
            get_translation_provider(provider_name=provider_name).get_languages()
        )
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/translation/settings")
def translation_settings():
    provider = default_project_translation_provider()
    return jsonify({
        "provider": provider,
        "providers": translation_provider_options(),
        "model": current_app.config.get("HY_MT_MODEL", "Hy-MT2-7B"),
        **_translation_setting_defaults(),
    })


@api_bp.get("/diagnostics")
def diagnostics():
    report = run_system_diagnostics(
        deep=_parse_bool_query(request.args.get("deep")),
        refresh=_parse_bool_query(request.args.get("refresh")),
    )
    return jsonify(report.to_dict(include_details=False)), 200 if report.ready else 503


@api_bp.get("/projects/<project_id>")
def get_project(project_id):
    project = _project_or_404(project_id)
    names = _translation_language_names(project.translation_provider)
    return jsonify(project.to_dict(language_names=names))


@api_bp.patch("/projects/<project_id>")
def update_project(project_id):
    project = _project_or_404(project_id)
    payload = request.get_json(silent=True) or {}
    translation_selection = _parse_project_translation_selection(project, payload)
    if "glossary" in payload:
        project.glossary = str(payload.get("glossary") or "").strip() or None
    if "detect_speakers" in payload:
        project.detect_speakers = _parse_bool_value(payload["detect_speakers"])
    if "smooth_speaker_fragments" in payload:
        project.smooth_speaker_fragments = _parse_bool_value(
            payload["smooth_speaker_fragments"]
        )
    if translation_selection:
        provider_name, target_language = translation_selection
        selection_changed = (
            provider_name != project.translation_provider
            or target_language != project.target_language
        )
        project.translation_provider = provider_name
        project.target_language = target_language
        if selection_changed:
            project.translation_needs_reprocessing = (
                bool(project.translation_needs_reprocessing) or bool(project.segments)
            )
            _invalidate_project_outputs(project)
    if "translation_settings" in payload:
        settings = payload.get("translation_settings")
        if not isinstance(settings, dict):
            abort(400, description="translation_settings must be an object")
        _apply_translation_settings(project, settings)
    db.session.commit()
    names = _translation_language_names(project.translation_provider)
    return jsonify(project.to_dict(language_names=names))


@api_bp.delete("/projects/<project_id>")
def delete_project(project_id):
    project = _project_or_404(project_id)
    paths = [project.source_video_path, project.extracted_audio_path, project.output_video_path, project.srt_path]
    db.session.delete(project)
    db.session.commit()
    _delete_project_artifacts(paths)
    return "", 204


@api_bp.post("/projects/<project_id>/video")
def upload_video(project_id):
    project = _project_or_404(project_id)
    upload = request.files.get("video")
    if not upload or not upload.filename:
        return jsonify({"error": "Upload a video file with form field 'video'"}), 400
    try:
        path = save_video_upload(upload, Path(current_app.config["STORAGE_DIR"]) / "uploads")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    project.source_video_path = str(path)
    project.status = ProjectStatus.UPLOADED
    project.processing_stage = None
    project.processing_warning = None
    project.error_message = None
    db.session.commit()
    return jsonify(project.to_dict())


@api_bp.post("/projects/<project_id>/process")
def process_project(project_id):
    project = _project_or_404(project_id)
    if not project.source_video_path:
        return jsonify({"error": "Upload a video before processing"}), 400
    try:
        require_job_preflight("process", project)
    except PreflightError as exc:
        return jsonify({"error": str(exc), "diagnostics": exc.report.to_dict(include_details=False)}), 503
    from .tasks import process_video_task

    project.status = ProjectStatus.PROCESSING
    project.processing_stage = "queued"
    project.processing_warning = None
    project.translation_completed_words = 0
    project.translation_total_words = 0
    project.error_message = None
    db.session.commit()
    task = process_video_task.delay(project.id)
    return jsonify({"task_id": task.id, "project": project.to_dict()}), 202


@api_bp.get("/projects/<project_id>/segments")
def list_segments(project_id):
    _project_or_404(project_id)
    segments = SubtitleSegment.query.filter_by(project_id=project_id).order_by(SubtitleSegment.segment_index.asc()).all()
    return jsonify([segment.to_dict() for segment in segments])


@api_bp.get("/projects/<project_id>/transcript/words")
def list_transcript_words(project_id):
    _project_or_404(project_id)
    words = TranscriptWordRecord.query.filter_by(project_id=project_id).order_by(TranscriptWordRecord.word_index).all()
    return jsonify([word.to_dict() for word in words])


@api_bp.patch("/segments/<segment_id>")
def update_segment(segment_id):
    segment = SubtitleSegment.query.get(segment_id)
    if not segment:
        abort(404, description="Subtitle segment not found")
    payload = request.get_json(silent=True) or {}
    changed = False
    if "translated_text" in payload:
        value = str(payload["translated_text"])
        changed = changed or value != segment.translated_text
        segment.translated_text = value
    if "speaker_label" in payload:
        value = payload["speaker_label"]
        next_speaker = (str(value).strip() or None) if value is not None else None
        changed = changed or next_speaker != segment.speaker_label
        segment.speaker_label = next_speaker
    if "start_time" in payload:
        value = _parse_time(payload["start_time"], "start_time")
        changed = changed or value != segment.start_time
        segment.start_time = value
    if "end_time" in payload:
        value = _parse_time(payload["end_time"], "end_time")
        changed = changed or value != segment.end_time
        segment.end_time = value
    if segment.start_time >= segment.end_time:
        return jsonify({"error": "start_time must be less than end_time"}), 400
    if changed:
        _invalidate_project_outputs(segment.project)
    db.session.commit()
    return jsonify(segment.to_dict())


@api_bp.post("/projects/<project_id>/export/srt")
def export_srt(project_id):
    project = _project_or_404(project_id)
    if project.translation_needs_reprocessing:
        return jsonify({"error": "Reprocess the project before exporting updated subtitles"}), 400
    try:
        srt_path = generate_srt(project.id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    project.srt_path = str(srt_path)
    db.session.commit()
    return jsonify({"srt_path": str(srt_path), "download_url": f"/api/projects/{project.id}/export/srt/download"})


@api_bp.get("/projects/<project_id>/export/srt/download")
def download_srt(project_id):
    return _send_existing_file(_project_or_404(project_id).srt_path, as_attachment=True)


@api_bp.post("/projects/<project_id>/render")
def render_project(project_id):
    project = _project_or_404(project_id)
    if not project.source_video_path:
        return jsonify({"error": "Upload a video before rendering"}), 400
    if not project.segments:
        return jsonify({"error": "Process the video before rendering"}), 400
    if project.translation_needs_reprocessing:
        return jsonify({"error": "Reprocess the project before rendering updated subtitles"}), 400
    try:
        require_job_preflight("render", project)
    except PreflightError as exc:
        return jsonify({"error": str(exc), "diagnostics": exc.report.to_dict(include_details=False)}), 503
    from .tasks import render_video_task

    project.status = ProjectStatus.RENDERING
    project.processing_stage = "queued_render"
    project.error_message = None
    db.session.commit()
    task = render_video_task.delay(project.id)
    return jsonify({"task_id": task.id, "project": project.to_dict()}), 202


@api_bp.get("/projects/<project_id>/download")
def download_render(project_id):
    return _send_existing_file(_project_or_404(project_id).output_video_path, as_attachment=True)


@api_bp.get("/projects/<project_id>/status")
def project_status(project_id):
    project = _project_or_404(project_id)
    data = project.to_dict()
    return jsonify({
        "id": project.id,
        "status": project.status,
        "processing_stage": project.processing_stage,
        "processing_warning": project.processing_warning,
        "translation_progress": data["translation_progress"],
        "error_message": project.error_message,
        "updated_at": data["updated_at"],
    })


@api_bp.get("/projects/<project_id>/media/source")
def source_media(project_id):
    return _send_existing_file(_project_or_404(project_id).source_video_path)


@api_bp.get("/projects/<project_id>/media/rendered")
def rendered_media(project_id):
    return _send_existing_file(_project_or_404(project_id).output_video_path)


def _project_or_404(project_id):
    project = Project.query.get(project_id)
    if not project:
        abort(404, description="Project not found")
    return project


def _parse_time(value, field_name):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        abort(400, description=f"{field_name} must be a number")
    if parsed < 0:
        abort(400, description=f"{field_name} cannot be negative")
    return parsed


def _parse_optional_int(value, field_name):
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        abort(400, description=f"{field_name} must be an integer")
    if parsed < 1:
        abort(400, description=f"{field_name} must be at least 1")
    return parsed


def _parse_bool_query(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _apply_translation_settings(project, values, defaults=None):
    if not isinstance(values, dict):
        abort(400, description="translation_settings must be an object")
    defaults = defaults or {}
    fields = {
        "temperature": ("translation_temperature", float, 0, 2),
        "top_p": ("translation_top_p", float, 0.01, 1),
        "top_k": ("translation_top_k", int, 0, 500),
        "repetition_penalty": ("translation_repetition_penalty", float, 0.5, 2),
        "max_tokens": ("translation_max_tokens", int, 16, 2048),
        "context_captions": ("translation_context_captions", int, 0, 5),
    }
    for public_name, (attribute, cast, minimum, maximum) in fields.items():
        if public_name not in values and public_name not in defaults:
            continue
        raw = values.get(public_name, defaults.get(public_name))
        try:
            parsed = cast(raw)
        except (TypeError, ValueError):
            abort(400, description=f"translation_settings.{public_name} must be a number")
        if parsed < minimum or parsed > maximum:
            abort(
                400,
                description=(
                    f"translation_settings.{public_name} must be between "
                    f"{minimum} and {maximum}"
                ),
            )
        setattr(project, attribute, parsed)


def _parse_translation_provider(value):
    if value in (None, ""):
        return default_project_translation_provider()
    provider = normalize_project_translation_provider(value)
    if not provider:
        valid = ", ".join(provider["id"] for provider in translation_provider_options())
        abort(400, description=f"translation_provider must be one of: {valid}")
    return provider


def _parse_project_translation_selection(project, payload):
    if "translation_provider" not in payload and "target_language" not in payload:
        return None
    if project.status in {ProjectStatus.PROCESSING, ProjectStatus.RENDERING}:
        abort(
            400,
            description=(
                "Cannot update translation engine or target language while a job is active"
            ),
        )

    provider_name = (
        _parse_translation_provider(payload.get("translation_provider"))
        if "translation_provider" in payload
        else _parse_translation_provider(project.translation_provider)
    )
    raw_target = (
        payload.get("target_language")
        if "target_language" in payload
        else project.target_language
    )
    target_language = normalize_translation_language(raw_target)
    if not target_language or target_language == "auto":
        abort(400, description="target_language must be a supported language code")

    _validate_project_translation_languages(
        provider_name,
        project.source_language,
        target_language,
    )
    return provider_name, target_language


def _validate_project_translation_languages(
    provider_name, source_language, target_language,
):
    try:
        languages = get_translation_provider(
            provider_name=provider_name
        ).get_languages()
    except RuntimeError as exc:
        abort(503, description=str(exc))
    except ValueError as exc:
        abort(400, description=str(exc))

    catalog = {}
    for language in languages:
        if not isinstance(language, dict):
            continue
        code = normalize_translation_language(language.get("code"))
        if code:
            catalog[code] = language

    if target_language not in catalog:
        abort(
            400,
            description=(
                f"{provider_name} does not support target language {target_language}"
            ),
        )

    source_code = normalize_translation_language(source_language)
    if not source_code:
        abort(400, description="Project source language is invalid")
    if source_code == "auto":
        return
    source = catalog.get(source_code)
    if not source:
        abort(
            400,
            description=f"{provider_name} does not support source language {source_code}",
        )
    if isinstance(source.get("targets"), list):
        targets = {
            code
            for value in source["targets"]
            if (code := normalize_translation_language(value))
        }
        if target_language not in targets:
            abort(
                400,
                description=(
                    f"{provider_name} does not support translation from "
                    f"{source_code} to {target_language}"
                ),
            )


def _translation_setting_defaults():
    return {
        "temperature": current_app.config.get("HY_MT_TEMPERATURE", 0.7),
        "top_p": current_app.config.get("HY_MT_TOP_P", 0.6),
        "top_k": current_app.config.get("HY_MT_TOP_K", 20),
        "repetition_penalty": current_app.config.get("HY_MT_REPETITION_PENALTY", 1.05),
        "max_tokens": current_app.config.get("HY_MT_MAX_TOKENS", 256),
        "context_captions": current_app.config.get("HY_MT_CONTEXT_CAPTIONS", 2),
    }


def _parse_bool_value(value):
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"", "0", "false", "no", "off"}:
        return False
    abort(400, description="Boolean project options must be true or false")


def _send_existing_file(path, as_attachment=False):
    if not path or not Path(path).exists():
        abort(404, description="File not found")
    return send_file(path, as_attachment=as_attachment)


def _translation_language_names(provider_name=None):
    try:
        languages = get_translation_provider(provider_name=provider_name).get_languages()
    except (RuntimeError, ValueError):
        return {}
    return {
        str(item["code"]).strip().lower().replace("_", "-"): str(item.get("name") or item["code"])
        for item in languages if isinstance(item, dict) and item.get("code")
    }


def _delete_project_artifacts(paths):
    storage_dir = Path(current_app.config["STORAGE_DIR"]).resolve()
    for value in paths:
        if not value:
            continue
        path = Path(value).resolve()
        if path == storage_dir or storage_dir not in path.parents:
            current_app.logger.warning("Skipped deleting project artifact outside storage: %s", path)
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.exception("Could not delete project artifact: %s", path)


def _invalidate_project_outputs(project):
    paths = [project.srt_path, project.output_video_path]
    project.srt_path = None
    project.output_video_path = None
    if project.status == ProjectStatus.RENDERED:
        project.status = ProjectStatus.PROCESSED
    _delete_project_artifacts(paths)
