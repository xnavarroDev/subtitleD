import pytest

from app import create_app
from app import tasks
from app.extensions import db
from app.models import Project, ProjectStatus, SubtitleSegment, TranscriptWordRecord
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


def test_processing_preserves_whisperx_text_and_uses_deterministic_result(app, monkeypatch):
    with app.app_context():
        source = app.config["STORAGE_DIR"] / "uploads" / "source.mp4"
        source.write_bytes(b"video")
        project = Project(
            title="Context demo", source_language="en", target_language="es",
            source_video_path=str(source), status=ProjectStatus.UPLOADED,
            translation_provider="libretranslate",
            translation_needs_reprocessing=True,
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

    class Libre:
        def translate(self, text, source, target):
            return {
                "Hello there friend": "Hola amigo",
                "Hello there": "Hola",
                "friend": "amigo",
            }[text]

    monkeypatch.setattr(tasks, "require_job_preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks, "extract_audio", lambda source, output: output.write_bytes(b"audio"))
    monkeypatch.setattr(tasks, "get_transcription_provider", lambda: Transcriber())
    provider_calls = []

    def get_provider(settings=None, provider_name=None):
        provider_calls.append((settings, provider_name))
        return Libre()

    monkeypatch.setattr(tasks, "get_translation_provider", get_provider)

    with app.app_context():
        tasks.process_video_task.run(project_id)
        project = db.session.get(Project, project_id)

        assert project.status == ProjectStatus.PROCESSED
        assert project.translation_completed_words == 3
        assert [segment.original_text for segment in project.segments] == ["Hello there friend"]
        assert [segment.translated_text for segment in project.segments] == ["Hola amigo"]
        assert project.segments[0].transcription_confidence == pytest.approx(0.8)
        assert project.processing_warning is None
        assert project.translation_needs_reprocessing is False
        assert [word.raw_text for word in project.transcript_words] == ["Hello", "there", "friend"]
        assert all(isinstance(word, TranscriptWordRecord) for word in project.transcript_words)
        assert provider_calls[0][1] == "libretranslate"


def test_failed_reprocessing_preserves_previous_subtitles(app, monkeypatch):
    with app.app_context():
        source = app.config["STORAGE_DIR"] / "uploads" / "source.mp4"
        source.write_bytes(b"video")
        project = Project(title="Existing", source_language="en", target_language="es", source_video_path=str(source), status=ProjectStatus.PROCESSED, translation_needs_reprocessing=True)
        db.session.add(project)
        db.session.flush()
        db.session.add(SubtitleSegment(project_id=project.id, start_time=0, end_time=1, original_text="Old", translated_text="Anterior", segment_index=0))
        db.session.commit()
        project_id = project.id

    class Transcriber:
        def transcribe(self, *args, **kwargs):
            return [TranscriptSegment(0, 1, "New", words=(TranscriptWord("New", 0, 1, confidence=.9),))]

    class BrokenFallback:
        def translate(self, *args):
            raise RuntimeError("fallback offline")

    monkeypatch.setattr(tasks, "require_job_preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks, "extract_audio", lambda source, output: output.write_bytes(b"audio"))
    monkeypatch.setattr(tasks, "get_transcription_provider", lambda: Transcriber())
    monkeypatch.setattr(tasks, "get_translation_provider", lambda *_args, **_kwargs: BrokenFallback())

    with app.app_context(), pytest.raises(RuntimeError):
        tasks.process_video_task.run(project_id)
    with app.app_context():
        project = db.session.get(Project, project_id)
        assert project.status == ProjectStatus.PROCESSED
        assert project.translation_needs_reprocessing is True
        assert [(item.original_text, item.translated_text) for item in project.segments] == [("Old", "Anterior")]
