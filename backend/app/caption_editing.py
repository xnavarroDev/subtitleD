"""Reversible caption structure edits, separate from immutable WhisperX words."""
import math

from flask import Blueprint, abort, jsonify, request

from .extensions import db
from .models import Project, ProjectStatus, SubtitleSegment
from .providers import get_translation_provider
from .routes import _invalidate_project_outputs, _project_or_404, _require_idle

caption_edit_bp = Blueprint("caption_edit", __name__, url_prefix="/api")
FIELDS = (
    "start_time", "end_time", "original_text", "translated_text", "speaker_label",
    "transcription_confidence", "translation_method", "timing_quality", "translation_provider",
    "translation_model", "source_reconstruction_method", "source_was_reconstructed",
    "translation_unit_id", "translation_confidence_warning", "merge_parts",
)


def _payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="A JSON object is required.")
    return data


def _lock_project(project_id):
    # A conditional write serializes structure edits with job reservation, including
    # on SQLite, whose SELECT FOR UPDATE is not supported.
    changed = Project.query.filter(Project.id == project_id, Project.status.notin_([
        ProjectStatus.PROCESSING, ProjectStatus.RENDERING,
    ])).update({Project.updated_at: Project.updated_at}, synchronize_session=False)
    if not changed:
        abort(409, description="Wait for the current processing job to finish.")
    return _project_or_404(project_id)


def _rows(project_id):
    return SubtitleSegment.query.filter_by(project_id=project_id).order_by(SubtitleSegment.segment_index).all()


def _revision(row, revision):
    if not revision or revision != row.to_dict()["updated_at"]:
        abort(409, description="This caption changed in another session. Refresh before editing its structure.")


def _finish(project, rows):
    for index, row in enumerate(rows):
        row.segment_index = index
    _invalidate_project_outputs(project)
    db.session.commit()
    return jsonify([row.to_dict() for row in rows])


@caption_edit_bp.post("/projects/<project_id>/segments/merge")
def merge(project_id):
    data = _payload()
    ids = data.get("segment_ids")
    revisions = data.get("revisions")
    if not isinstance(ids, list) or not 2 <= len(ids) <= 20 or not all(isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
        abort(400, description="Select between 2 and 20 adjacent captions.")
    if not isinstance(revisions, dict):
        abort(400, description="Caption revisions are required.")
    project = _lock_project(project_id)
    rows = _rows(project_id)
    positions = [index for index, row in enumerate(rows) if row.id in ids]
    if len(positions) != len(ids) or positions != list(range(positions[0], positions[-1] + 1)):
        abort(400, description="Only adjacent captions from this project can be combined.")
    chosen = [rows[index] for index in positions]
    for row in chosen:
        _revision(row, revisions.get(row.id))
    if sum(len(row.original_text) for row in chosen) > 16000:
        abort(400, description="Select a shorter passage to combine.")
    # Limit repeated nested merges while keeping every previous boundary recoverable.
    def depth(parts):
        return 0 if not parts else 1 + max(depth(part.get("merge_parts")) for part in parts)
    if any(depth(row.merge_parts) >= 12 for row in chosen):
        abort(400, description="Split this passage before combining it again.")
    snapshots = [{key: getattr(row, key) for key in FIELDS} for row in chosen]
    first = chosen[0]
    first.merge_parts = snapshots
    first.original_text = " ".join(row.original_text.strip() for row in chosen)
    first.translated_text = " ".join(row.translated_text.strip() for row in chosen)
    first.start_time = min(row.start_time for row in chosen)
    first.end_time = max(row.end_time for row in chosen)
    first.speaker_label = chosen[0].speaker_label if len({row.speaker_label for row in chosen}) == 1 else None
    first.translation_method = "manual_merge"
    first.translation_unit_id = None
    first.translation_confidence_warning = "Combined passage. Review wording and split into readable captions before export."
    for row in chosen[1:]:
        db.session.delete(row)
    remaining = [row for row in rows if row.id not in ids or row is first]
    return _finish(project, remaining)


@caption_edit_bp.post("/segments/<segment_id>/split")
def split(segment_id):
    data = _payload()
    segment = db.session.get(SubtitleSegment, segment_id)
    if not segment:
        abort(404, description="Caption not found.")
    project = _lock_project(segment.project_id)
    _revision(segment, data.get("revision"))
    parts = data.get("parts")
    if not isinstance(parts, list) or not 2 <= len(parts) <= 20 or not all(isinstance(part, dict) for part in parts):
        abort(400, description="Provide between 2 and 20 caption parts.")
    if segment.merge_parts:
        if len(parts) != len(segment.merge_parts):
            abort(400, description="Keep the original caption boundaries when splitting this combined passage.")
        snapshots = segment.merge_parts
    else:
        snapshots = []
        previous = segment.start_time
        for part in parts:
            try:
                start, end = float(part["start_time"]), float(part["end_time"])
            except (ValueError, TypeError, KeyError):
                abort(400, description="Valid start and end times are required.")
            if not math.isfinite(start) or not math.isfinite(end) or abs(start - previous) > .001 or end <= start or end > segment.end_time + .001:
                abort(400, description="Split timings must cover this caption in order without gaps or overlaps.")
            source = part.get("original_text")
            if not isinstance(source, str) or not source.strip():
                abort(400, description="Each part needs its original transcript text.")
            snapshot = {key: getattr(segment, key) for key in FIELDS}
            snapshot.update(start_time=start, end_time=end, original_text=source.strip(), merge_parts=None, translation_method="manual_split", timing_quality="estimated")
            snapshots.append(snapshot)
            previous = end
        if abs(previous - segment.end_time) > .001 or "".join("".join(part["original_text"].split()) for part in parts) != "".join(segment.original_text.split()):
            abort(400, description="The split must preserve the full transcript and time range.")
    replacements = []
    for part, snapshot in zip(parts, snapshots):
        text = part.get("translated_text")
        if not isinstance(text, str) or not text.strip() or len(text) > 16000:
            abort(400, description="Distribute the translation into every caption before saving the split.")
        values = dict(snapshot)
        values["translated_text"] = text.strip()
        if text.strip() != snapshot["translated_text"]:
            values.update(translation_provider=segment.translation_provider, translation_model=segment.translation_model,
                          translation_method="manual_split", translation_confidence_warning="Translation redistributed manually; review against the video.")
        replacements.append(SubtitleSegment(project_id=project.id, **values))
    rows = _rows(project.id)
    position = rows.index(segment)
    db.session.delete(segment)
    db.session.add_all(replacements)
    return _finish(project, rows[:position] + replacements + rows[position + 1:])


@caption_edit_bp.post("/segments/<segment_id>/translate")
def translate_passage(segment_id):
    segment = db.session.get(SubtitleSegment, segment_id)
    if not segment:
        abort(404, description="Caption not found.")
    project = segment.project
    _require_idle(project)
    source_language = project.detected_source_language or project.source_language
    if source_language == "auto":
        abort(400, description="Choose or detect the source language before translating this passage.")
    rows = _rows(project.id)
    position = rows.index(segment)
    count = project.translation_context_captions
    before = tuple(row.original_text for row in rows[max(0, position - count):position])
    after = tuple(row.original_text for row in rows[position + 1:position + 1 + count])
    settings = project.to_dict()["translation_settings"] | {"glossary": project.glossary}
    provider = get_translation_provider(settings=settings, provider_name=project.translation_provider)
    readiness = provider.check_ready(source_language, project.target_language)
    if readiness.status == "fail":
        abort(503, description=readiness.message)
    try:
        if hasattr(provider, "translate_with_context"):
            output = provider.translate_with_context(segment.original_text, source_language, project.target_language, before, after)
        else:
            output = provider.translate_with_metadata(segment.original_text, source_language, project.target_language)
    except Exception as exc:
        current_message = str(exc)
        abort(503, description=f"Passage translation failed: {current_message}")
    # This is a preview. Saving and splitting are separate explicit user actions.
    return jsonify({"translated_text": output.text, "provider": output.provider, "model": output.model,
                    "warning": output.warning, "revision": segment.to_dict()["updated_at"],
                    "context_supported": output.provider == "hy-mt2-kobold"})
