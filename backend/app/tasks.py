from pathlib import Path
from uuid import uuid4

from flask import current_app

from .diagnostics import require_job_preflight
from .extensions import celery_app, db
from .models import Project, ProjectStatus, SubtitleSegment
from .providers import (
    get_contextual_translation_provider,
    get_transcription_provider,
    get_translation_provider,
)
from .providers.contextual_translation import ContextCaption
from .providers.translation import normalize_language as normalize_translation_language
from .utils.captions import flatten_transcript_words
from .utils.contextual_translation import iter_contextual_translation
from .utils.ffmpeg import burn_subtitles, extract_audio
from .utils.srt import generate_srt


class _IdentityTranslationProvider:
    def translate(self, text, source_language, target_language):
        return text


class _IdentityContextualProvider:
    def __init__(self, max_duration, max_chars):
        self.max_duration = float(max_duration)
        self.max_chars = int(max_chars)

    def translate_window(self, words, *args, **kwargs):
        captions = []
        start = 0
        while start < len(words):
            end = start
            while end + 1 < len(words):
                span = words[start:end + 2]
                text = " ".join(word.text for word in span)
                speakers = {word.speaker_label for word in span if word.speaker_label}
                if (
                    len(speakers) > 1
                    or span[-1].end_time - span[0].start_time > self.max_duration
                    or len(text) > self.max_chars
                ):
                    break
                end += 1
            captions.append(ContextCaption(words[start].id, words[end].id, " ".join(word.text for word in words[start:end + 1])))
            start = end + 1
        return captions


@celery_app.task(name="process_video_task")
def process_video_task(project_id):
    """Transcribe raw words, then translate and segment them with sliding context."""
    project = Project.query.get(project_id)
    if not project:
        return {"error": "Project not found"}

    try:
        require_job_preflight("process", project, include_worker=False)
        _set_processing(project, "extracting_audio")

        if not project.source_video_path:
            raise ValueError("Project has no uploaded source video")

        storage_dir = Path(current_app.config["STORAGE_DIR"])
        audio_path = storage_dir / "audio" / f"{project.id}-{uuid4().hex}.wav"
        extract_audio(project.source_video_path, audio_path)
        project.extracted_audio_path = str(audio_path)
        project.processing_stage = "transcribing"
        db.session.commit()

        transcript = get_transcription_provider().transcribe(
            audio_path,
            project.source_language,
            min_speakers=project.min_speakers,
            max_speakers=project.max_speakers,
        )
        words = flatten_transcript_words(transcript)
        if not words:
            raise ValueError("Transcription produced no timed words")

        SubtitleSegment.query.filter_by(project_id=project.id).delete(
            synchronize_session=False
        )
        project.translation_total_words = len(words)
        project.translation_completed_words = 0
        project.processing_stage = "contextual_translation"
        db.session.commit()

        same_language = (
            normalize_translation_language(project.source_language)
            == normalize_translation_language(project.target_language)
            and normalize_translation_language(project.source_language) != "auto"
        )
        contextual = (
            _IdentityContextualProvider(
                current_app.config["CAPTION_MAX_DURATION_SECONDS"],
                current_app.config["CAPTION_MAX_CHARS"],
            )
            if same_language else get_contextual_translation_provider()
        )
        fallback = _IdentityTranslationProvider() if same_language else get_translation_provider()
        warnings = []
        segment_index = 0
        for batch, completed_words, warning in iter_contextual_translation(
            words,
            contextual,
            fallback,
            project.source_language,
            project.target_language,
            window_seconds=current_app.config["TRANSLATION_WINDOW_SECONDS"],
            lookahead_seconds=current_app.config["TRANSLATION_LOOKAHEAD_SECONDS"],
            context_caption_count=current_app.config["TRANSLATION_CONTEXT_CAPTIONS"],
            max_duration=current_app.config["CAPTION_MAX_DURATION_SECONDS"],
            max_chars=current_app.config["CAPTION_MAX_CHARS"],
        ):
            for caption in batch:
                db.session.add(
                    SubtitleSegment(
                        project_id=project.id,
                        start_time=caption.start_time,
                        end_time=caption.end_time,
                        original_text=caption.original_text,
                        translated_text=caption.translated_text,
                        speaker_label=caption.speaker_label,
                        transcription_confidence=caption.transcription_confidence,
                        segment_index=segment_index,
                    )
                )
                segment_index += 1
            if warning:
                warnings.append(warning)
            project.translation_completed_words = completed_words
            project.processing_warning = _warning_text(warnings)
            db.session.commit()

        project.status = ProjectStatus.PROCESSED
        project.processing_stage = "complete"
        project.translation_completed_words = len(words)
        project.processing_warning = _warning_text(warnings)
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
        project.processing_stage = "rendering"
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
        project.processing_stage = "complete"
        db.session.commit()
        return {"project_id": project.id, "status": project.status}
    except Exception as exc:
        _mark_failed(project_id, exc)
        raise


def _set_processing(project, stage):
    project.status = ProjectStatus.PROCESSING
    project.processing_stage = stage
    project.processing_warning = None
    project.translation_completed_words = 0
    project.translation_total_words = 0
    project.error_message = None
    db.session.commit()


def _warning_text(warnings):
    if not warnings:
        return None
    unique = list(dict.fromkeys(warnings))
    first_issue = unique[0].split(": ", 1)[-1]
    return (
        f"Contextual translation used the deterministic fallback in {len(unique)} "
        f"window(s). First issue: {first_issue}"
    )[:1000]


def _mark_failed(project_id, exc):
    """Persist failure status after rolling back any partial DB transaction."""
    current_app.logger.exception("Project job failed: %s", exc)
    db.session.rollback()
    project = Project.query.get(project_id)
    if project:
        project.status = ProjectStatus.FAILED
        project.processing_stage = "failed"
        project.error_message = str(exc)[:1000]
        db.session.commit()
