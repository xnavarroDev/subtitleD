import pytest

from app import create_app
from app import tasks
from app.extensions import db
from app.models import Project, ProjectStatus
from app.providers.contextual_translation import ContextCaption
from app.providers.transcription import TranscriptSegment, TranscriptWord


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    CORS_ORIGINS = ["http://localhost:5173"]
    CREATE_TABLES = True
    TRANSLATION_PROVIDER = "mock"
    TRANSLATION_WINDOW_SECONDS = 20
    TRANSLATION_LOOKAHEAD_SECONDS = 4
    TRANSLATION_CONTEXT_CAPTIONS = 2
    CAPTION_MAX_DURATION_SECONDS = 6
    CAPTION_MAX_CHARS = 84


@pytest.fixture()
def app(tmp_path):
    class Config(TestConfig):
        STORAGE_DIR = tmp_path / "storage"

    app = create_app(Config)
    with app.app_context():
        yield app
        db.session.remove()
        db.drop_all()


def test_processing_preserves_whisperx_text_and_uses_contextual_result(app, monkeypatch):
    with app.app_context():
        source = app.config["STORAGE_DIR"] / "uploads" / "source.mp4"
        source.write_bytes(b"video")
        project = Project(
            title="Context demo", source_language="en", target_language="es",
            source_video_path=str(source), status=ProjectStatus.UPLOADED,
        )
        db.session.add(project)
        db.session.commit()
        project_id = project.id

    transcript = [TranscriptSegment(
        0.0, 1.5, "Hello there friend", "A",
        (
            TranscriptWord("Hello", 0.0, 0.4, "A", 0.9),
            TranscriptWord("there", 0.5, 0.9, "A", 0.8),
            TranscriptWord("friend", 1.0, 1.5, "A", 0.7),
        ),
    )]

    class Transcriber:
        def transcribe(self, *args, **kwargs):
            return transcript

    class Contextual:
        def translate_window(self, words, previous, source, target):
            assert previous == []
            return [
                ContextCaption(words[0].id, words[1].id, "Hola"),
                ContextCaption(words[2].id, words[2].id, "amigo"),
            ]

    class Fallback:
        def translate(self, *args):
            raise AssertionError("fallback should not run")

    monkeypatch.setattr(tasks, "require_job_preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks, "extract_audio", lambda source, output: output.write_bytes(b"audio"))
    monkeypatch.setattr(tasks, "get_transcription_provider", lambda: Transcriber())
    monkeypatch.setattr(tasks, "get_contextual_translation_provider", lambda: Contextual())
    monkeypatch.setattr(tasks, "get_translation_provider", lambda: Fallback())

    with app.app_context():
        tasks.process_video_task.run(project_id)
        project = db.session.get(Project, project_id)

        assert project.status == ProjectStatus.PROCESSED
        assert project.translation_completed_words == 3
        assert [segment.original_text for segment in project.segments] == ["Hello there", "friend"]
        assert [segment.translated_text for segment in project.segments] == ["Hola", "amigo"]
        assert project.segments[0].transcription_confidence == pytest.approx(0.85)
        assert project.processing_warning is None
