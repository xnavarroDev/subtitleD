from pathlib import Path
from uuid import uuid4

from flask import current_app

from .diagnostics import require_job_preflight
from .extensions import celery_app, db
from .models import Project, ProjectStatus, SubtitleSegment, TranscriptWordRecord
from .providers import (
    get_transcription_provider,
    get_translation_provider,
)
from .providers.translation import (
    default_project_translation_provider,
    normalize_language as normalize_translation_language,
)
from .utils.captions import flatten_transcript_words
from .utils.caption_translation import iter_deterministic_translation
from .utils.source_reconstruction import reconstruct_source_words
from .utils.ffmpeg import burn_subtitles, extract_audio
from .utils.srt import generate_srt


class _IdentityTranslationProvider:
    provider_name = "identity"

    def translate(self, text, source_language, target_language):
        return text


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
        project.processing_stage = (
            "loading_japanese_alignment"
            if normalize_translation_language(project.source_language) == "ja"
            else "transcribing"
        )
        db.session.commit()

        transcriber = get_transcription_provider()
        transcript = transcriber.transcribe(
            audio_path,
            project.source_language,
            min_speakers=project.min_speakers,
            max_speakers=project.max_speakers,
            glossary=project.glossary,
            diarize=project.detect_speakers,
        )
        words = flatten_transcript_words(transcript)
        transcription_warnings = list(getattr(transcriber, "last_warnings", []))
        project.detected_source_language = getattr(
            transcriber, "last_detected_language", None
        ) or normalize_translation_language(project.source_language)
        if not words:
            raise ValueError("Transcription produced no timed words")

        project.translation_total_words = len(words)
        project.translation_completed_words = 0
        project.processing_stage = "segmenting_and_translating"
        db.session.commit()

        reconstruction = _reconstruct_words(project, words)
        prepared, warnings = _translate_words(project, reconstruction.words)
        warnings = [
            *transcription_warnings,
            *([reconstruction.warning] if reconstruction.warning else []),
            *warnings,
        ]
        artifact_paths = [project.srt_path, project.output_video_path]

        # Replace successful output in one transaction. A failed translation leaves
        # the previous transcript, subtitles, and exports registered.
        SubtitleSegment.query.filter_by(project_id=project.id).delete(synchronize_session=False)
        TranscriptWordRecord.query.filter_by(project_id=project.id).delete(synchronize_session=False)
        for index, word in enumerate(words):
            db.session.add(TranscriptWordRecord(
                project_id=project.id, word_index=index, raw_text=word.text,
                start_time=word.start_time, end_time=word.end_time,
                speaker_label=word.speaker_label, confidence=word.confidence,
                timing_quality=word.timing_quality,
            ))
        _add_segments(project, prepared)
        project.srt_path = None
        project.output_video_path = None
        project.status = ProjectStatus.PROCESSED
        project.processing_stage = "complete"
        project.translation_needs_reprocessing = False
        project.translation_completed_words = len(words)
        project.processing_warning = _warning_text(warnings)
        db.session.commit()
        _delete_artifacts(artifact_paths)
        return {"project_id": project.id, "status": project.status}
    except Exception as exc:
        _mark_failed(project_id, exc, preserve_existing=True)
        raise


def _translate_words(project, words):
    effective_source_language = (
        project.detected_source_language
        if normalize_translation_language(project.source_language) == "auto"
        else project.source_language
    )
    same_language = (
        normalize_translation_language(effective_source_language)
        == normalize_translation_language(project.target_language)
        and normalize_translation_language(effective_source_language) != "auto"
    )
    translator = (
        _IdentityTranslationProvider()
        if same_language
        else get_translation_provider(
            _project_translation_settings(project),
            provider_name=(
                project.translation_provider or default_project_translation_provider()
            ),
        )
    )
    if not same_language and hasattr(translator, "check_ready"):
        readiness = translator.check_ready(
            effective_source_language, project.target_language
        )
        if readiness.status == "fail":
            raise RuntimeError(readiness.message)
    warnings = []
    prepared = []
    for batch, completed_words, warning in iter_deterministic_translation(
        words,
        translator,
        effective_source_language,
        project.target_language,
        max_duration=current_app.config["CAPTION_MAX_DURATION_SECONDS"],
        max_chars=current_app.config["CAPTION_MAX_CHARS"],
        pause_seconds=current_app.config.get("CAPTION_PAUSE_SECONDS", 0.65),
        review_confidence_threshold=current_app.config.get(
            "SOURCE_REVIEW_CONFIDENCE_THRESHOLD", 0.45
        ),
        translation_unit_max_seconds=current_app.config.get(
            "TRANSLATION_UNIT_MAX_SECONDS", 12
        ),
        context_captions=project.translation_context_captions,
    ):
        prepared.extend(batch)
        if warning:
            warnings.append(warning)
        project.translation_completed_words = completed_words
        project.processing_warning = _warning_text(warnings)
        db.session.commit()
    return prepared, warnings


def _project_translation_settings(project):
    return {
        "temperature": project.translation_temperature,
        "top_p": project.translation_top_p,
        "top_k": project.translation_top_k,
        "repetition_penalty": project.translation_repetition_penalty,
        "max_tokens": project.translation_max_tokens,
        "glossary": project.glossary,
    }


def _reconstruct_words(project, words):
    return reconstruct_source_words(
        words,
        enabled=bool(project.smooth_speaker_fragments),
        max_gap_seconds=current_app.config.get(
            "SOURCE_RECONSTRUCTION_MAX_GAP_SECONDS", 0.2
        ),
        max_fragment_chars=current_app.config.get(
            "SOURCE_RECONSTRUCTION_MAX_FRAGMENT_CHARS", 2
        ),
        low_confidence_threshold=current_app.config.get(
            "SOURCE_REVIEW_CONFIDENCE_THRESHOLD", 0.45
        ),
    )


def _add_segments(project, prepared):
    for index, caption in enumerate(prepared):
        db.session.add(SubtitleSegment(
            project_id=project.id, start_time=caption.start_time, end_time=caption.end_time,
            original_text=caption.original_text, translated_text=caption.translated_text,
            speaker_label=caption.speaker_label,
            transcription_confidence=caption.transcription_confidence,
            translation_method=caption.translation_method, segment_index=index,
            timing_quality=caption.timing_quality,
            translation_provider=caption.translation_provider,
            translation_model=caption.translation_model,
            source_reconstruction_method=caption.source_reconstruction_method,
            source_was_reconstructed=caption.source_was_reconstructed,
            translation_unit_id=caption.translation_unit_id,
            translation_confidence_warning=caption.translation_confidence_warning,
        ))


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
    return " ".join(unique)[:1000]


def _mark_failed(project_id, exc, preserve_existing=False):
    """Persist failure status after rolling back any partial DB transaction."""
    current_app.logger.exception("Project job failed: %s", exc)
    db.session.rollback()
    project = Project.query.get(project_id)
    if project:
        project.status = ProjectStatus.PROCESSED if preserve_existing and project.segments else ProjectStatus.FAILED
        project.processing_stage = "failed"
        project.error_message = str(exc)[:1000]
        db.session.commit()


def _delete_artifacts(paths):
    storage_dir = Path(current_app.config["STORAGE_DIR"]).resolve()
    for value in paths:
        if not value:
            continue
        path = Path(value).resolve()
        if storage_dir in path.parents:
            path.unlink(missing_ok=True)
