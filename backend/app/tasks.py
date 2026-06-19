from pathlib import Path
from uuid import uuid4

from flask import current_app

from .diagnostics import require_job_preflight
from .extensions import celery_app, db
from .models import Project, ProjectStatus, SubtitleSegment
from .providers import get_transcription_provider, get_translation_provider
from .utils.ffmpeg import burn_subtitles, extract_audio
from .utils.srt import generate_srt


@celery_app.task(name="process_video_task")
def process_video_task(project_id):
    """Extract audio, transcribe it, translate segments, and persist results."""
    project = Project.query.get(project_id)
    if not project:
        return {"error": "Project not found"}

    try:
        require_job_preflight("process", project, include_worker=False)
        project.status = ProjectStatus.PROCESSING
        project.error_message = None
        db.session.commit()

        if not project.source_video_path:
            raise ValueError("Project has no uploaded source video")

        storage_dir = Path(current_app.config["STORAGE_DIR"])
        audio_path = storage_dir / "audio" / f"{project.id}-{uuid4().hex}.wav"

        # FFmpeg is isolated behind a utility function so render/extract settings
        # can evolve without changing the orchestration task.
        extract_audio(project.source_video_path, audio_path)
        project.extracted_audio_path = str(audio_path)
        db.session.commit()

        transcriber = get_transcription_provider()
        translator = get_translation_provider()
        transcript_segments = transcriber.transcribe(
            audio_path,
            project.source_language,
            min_speakers=project.min_speakers,
            max_speakers=project.max_speakers,
        )

        SubtitleSegment.query.filter_by(project_id=project.id).delete(
            synchronize_session=False
        )
        for index, segment in enumerate(transcript_segments):
            translated_text = translator.translate(
                segment.text, project.source_language, project.target_language
            )
            db.session.add(
                SubtitleSegment(
                    project_id=project.id,
                    start_time=segment.start_time,
                    end_time=segment.end_time,
                    original_text=segment.text,
                    translated_text=translated_text,
                    speaker_label=segment.speaker_label,
                    segment_index=index,
                )
            )

        project.status = ProjectStatus.PROCESSED
        db.session.commit()
        return {"project_id": project.id, "status": project.status}
    except Exception as exc:
        _mark_failed(project_id, exc)
        raise


@celery_app.task(name="render_video_task")
def render_video_task(project_id):
    """Generate subtitles when needed and burn them into the uploaded video."""
    project = Project.query.get(project_id)
    if not project:
        return {"error": "Project not found"}

    try:
        require_job_preflight("render", project, include_worker=False)
        project.status = ProjectStatus.RENDERING
        project.error_message = None
        db.session.commit()

        if not project.source_video_path:
            raise ValueError("Project has no uploaded source video")

        srt_path = generate_srt(project.id)
        output_path = (
            Path(current_app.config["STORAGE_DIR"])
            / "renders"
            / f"{project.id}-{uuid4().hex}.mp4"
        )

        burn_subtitles(project.source_video_path, srt_path, output_path)

        project.srt_path = str(srt_path)
        project.output_video_path = str(output_path)
        project.status = ProjectStatus.RENDERED
        db.session.commit()
        return {"project_id": project.id, "status": project.status}
    except Exception as exc:
        _mark_failed(project_id, exc)
        raise


def _mark_failed(project_id, exc):
    """Persist failure status after rolling back any partial DB transaction."""
    current_app.logger.exception("Project job failed: %s", exc)
    db.session.rollback()
    project = Project.query.get(project_id)
    if project:
        project.status = ProjectStatus.FAILED
        project.error_message = str(exc)[:1000]
        db.session.commit()
