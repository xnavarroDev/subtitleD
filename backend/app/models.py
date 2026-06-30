from datetime import datetime
from uuid import uuid4

from .extensions import db


class ProjectStatus:
    CREATED = "created"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    RENDERING = "rendering"
    RENDERED = "rendered"
    FAILED = "failed"


def _uuid():
    return str(uuid4())


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    title = db.Column(db.String(255), nullable=False)
    source_video_path = db.Column(db.String(1024), nullable=True)
    extracted_audio_path = db.Column(db.String(1024), nullable=True)
    output_video_path = db.Column(db.String(1024), nullable=True)
    srt_path = db.Column(db.String(1024), nullable=True)
    status = db.Column(db.String(32), nullable=False, default=ProjectStatus.CREATED)
    processing_stage = db.Column(db.String(64), nullable=True)
    processing_warning = db.Column(db.String(1000), nullable=True)
    translation_completed_words = db.Column(db.Integer, nullable=False, default=0)
    translation_total_words = db.Column(db.Integer, nullable=False, default=0)
    source_language = db.Column(db.String(64), nullable=False)
    target_language = db.Column(db.String(64), nullable=False)
    min_speakers = db.Column(db.Integer, nullable=True)
    max_speakers = db.Column(db.Integer, nullable=True)
    error_message = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    segments = db.relationship(
        "SubtitleSegment",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="SubtitleSegment.segment_index",
    )

    def to_dict(self, include_segments=False, language_names=None):
        language_names = language_names or {}
        total = int(self.translation_total_words or 0)
        completed = int(self.translation_completed_words or 0)
        data = {
            "id": self.id,
            "title": self.title,
            "source_video_path": self.source_video_path,
            "extracted_audio_path": self.extracted_audio_path,
            "output_video_path": self.output_video_path,
            "srt_path": self.srt_path,
            "status": self.status,
            "processing_stage": self.processing_stage,
            "processing_warning": self.processing_warning,
            "translation_progress": {"completed": completed, "total": total},
            "source_language": self.source_language,
            "target_language": self.target_language,
            "source_language_name": _language_display_name(self.source_language, language_names),
            "target_language_name": _language_display_name(self.target_language, language_names),
            "min_speakers": self.min_speakers,
            "max_speakers": self.max_speakers,
            "error_message": self.error_message,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "source_video_url": f"/api/projects/{self.id}/media/source" if self.source_video_path else None,
            "rendered_video_url": f"/api/projects/{self.id}/media/rendered" if self.output_video_path else None,
            "download_url": f"/api/projects/{self.id}/download" if self.output_video_path else None,
            "srt_download_url": f"/api/projects/{self.id}/export/srt/download" if self.srt_path else None,
        }
        if include_segments:
            data["segments"] = [segment.to_dict() for segment in self.segments]
        return data


def _language_display_name(value, language_names):
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized == "auto":
        return "Auto-detect"
    return language_names.get(normalized) or value


class SubtitleSegment(db.Model):
    __tablename__ = "subtitle_segments"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    project_id = db.Column(db.String(36), db.ForeignKey("projects.id"), nullable=False)
    start_time = db.Column(db.Float, nullable=False)
    end_time = db.Column(db.Float, nullable=False)
    original_text = db.Column(db.Text, nullable=False)
    translated_text = db.Column(db.Text, nullable=False)
    speaker_label = db.Column(db.String(64), nullable=True)
    transcription_confidence = db.Column(db.Float, nullable=True)
    segment_index = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship("Project", back_populates="segments")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "original_text": self.original_text,
            "translated_text": self.translated_text,
            "speaker_label": self.speaker_label,
            "transcription_confidence": self.transcription_confidence,
            "segment_index": self.segment_index,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }
