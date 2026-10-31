from types import SimpleNamespace
from io import BytesIO
from pathlib import Path

import pytest

from app import create_app, routes, tasks, diagnostics
from app.extensions import db
from app.models import Project, ProjectStatus, TranscriptWordRecord, SubtitleSegment
from app.providers.transcription import TranscriptSegment, TranscriptWord


@pytest.fixture()
def app(tmp_path):
    class Config:
        TESTING = True
        CREATE_TABLES = True
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        STORAGE_DIR = tmp_path
        CELERY_BROKER_URL = "memory://"
        CELERY_RESULT_BACKEND = "cache+memory://"
        CORS_ORIGINS = ["http://localhost:5173"]
        TRANSLATION_PROVIDER = "mock"
        CAPTION_MAX_DURATION_SECONDS = 6
        CAPTION_MAX_CHARS = 84
    application = create_app(Config)
    with application.app_context():
        source = tmp_path / "uploads" / "clip.mp4"
        source.write_bytes(b"video")
        project = Project(title="Local", source_language="en", target_language="es", source_video_path=str(source), status="uploaded")
        db.session.add(project)
        db.session.commit()
        application.config["PROJECT_ID"] = project.id
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


def fake_transcription(monkeypatch):
    monkeypatch.setattr(tasks, "require_job_preflight", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "extract_audio", lambda source, output: output.write_bytes(b"audio"))
    transcript = [TranscriptSegment(0, 1, "Hello friend.", words=(
        TranscriptWord("Hello", 0, .4, confidence=.9),
        TranscriptWord("friend.", .5, 1, confidence=.8),
    ))]
    monkeypatch.setattr(tasks, "get_transcription_provider", lambda: SimpleNamespace(transcribe=lambda *a, **k: transcript))


def test_transcribe_without_translator_then_translate_without_whisper_or_ffmpeg(app, monkeypatch):
    fake_transcription(monkeypatch)
    def unexpected(*args, **kwargs):
        pytest.fail("This stage used a dependency it should not require")
    monkeypatch.setattr(tasks, "get_translation_provider", unexpected)
    with app.app_context():
        project_id = app.config["PROJECT_ID"]
        tasks.process_video_task.run(project_id, mode="transcribe")
        project = db.session.get(Project, project_id)
        assert project.status == "transcribed"
        assert project.to_dict()["has_transcript"]
        assert project.translation_needs_reprocessing
        assert project.segments[0].original_text == "Hello friend."
        assert project.segments[0].translated_text == ""
        word_ids = [word.id for word in project.transcript_words]
        transcript_times = [(word.start_time, word.end_time) for word in project.transcript_words]
    monkeypatch.setattr(tasks, "get_transcription_provider", unexpected)
    monkeypatch.setattr(tasks, "extract_audio", unexpected)
    monkeypatch.setattr(tasks, "get_translation_provider", lambda *a, **k: SimpleNamespace(translate=lambda *args: "Hola amigo."))
    with app.app_context():
        tasks.translate_project_task.run(project_id)
        project = db.session.get(Project, project_id)
        assert project.status == "processed"
        assert not project.translation_needs_reprocessing
        assert project.segments[0].translated_text == "Hola amigo."
        assert [word.id for word in project.transcript_words] == word_ids
        assert [(word.start_time, word.end_time) for word in project.transcript_words] == transcript_times


def test_failed_translation_keeps_transcript_and_can_be_retried(app, monkeypatch):
    fake_transcription(monkeypatch)
    with app.app_context():
        project_id = app.config["PROJECT_ID"]
        tasks.process_video_task.run(project_id, mode="transcribe")
    def offline(*a, **k):
        raise RuntimeError("KoboldCpp offline")
    monkeypatch.setattr(tasks, "get_translation_provider", offline)
    with app.app_context(), pytest.raises(RuntimeError, match="offline"):
        tasks.translate_project_task.run(project_id)
    with app.app_context():
        project = db.session.get(Project, project_id)
        assert project.status == "transcribed"
        assert len(project.transcript_words) == 2
        assert project.segments[0].original_text == "Hello friend."
        assert project.translation_needs_reprocessing
    assert app.test_client().post(f"/api/projects/{project_id}/export/srt").status_code == 400


def test_queue_stages_and_duplicate_job_rejection(app, monkeypatch):
    monkeypatch.setattr(routes, "require_job_preflight", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(tasks.process_video_task, "delay", lambda *a, **k: (calls.append((a, k)) or SimpleNamespace(id="job")))
    client = app.test_client()
    path = f"/api/projects/{app.config['PROJECT_ID']}"
    assert client.post(path + "/translate").status_code == 400
    assert client.post(path + "/transcribe").status_code == 202
    assert calls[0][1] == {"mode": "transcribe"}
    assert client.post(path + "/transcribe").status_code == 409
    assert client.post(path + "/process").status_code == 409
    assert client.delete(path).status_code == 409
    assert client.post(path + "/video").status_code == 409
    assert len(calls) == 1


def test_broker_failure_does_not_leave_project_busy(app, monkeypatch):
    monkeypatch.setattr(routes, "require_job_preflight", lambda *a, **k: None)
    def unavailable(*a, **k):
        raise RuntimeError("broker unavailable")
    monkeypatch.setattr(tasks.process_video_task, "delay", unavailable)
    path = f"/api/projects/{app.config['PROJECT_ID']}"
    assert app.test_client().post(path + "/transcribe").status_code == 503
    with app.app_context():
        assert db.session.get(Project, app.config["PROJECT_ID"]).status == "failed"


def test_replacing_video_clears_saved_transcript_and_generated_outputs(app, monkeypatch):
    fake_transcription(monkeypatch)
    with app.app_context():
        project_id = app.config["PROJECT_ID"]
        tasks.process_video_task.run(project_id, mode="transcribe")
        project = db.session.get(Project, project_id)
        old_source = Path(project.source_video_path)
        output = app.config["STORAGE_DIR"] / "exports" / "old.srt"
        output.write_text("old subtitles")
        project.srt_path = str(output)
        db.session.commit()
    response = app.test_client().post(f"/api/projects/{project_id}/video", data={
        "video": (BytesIO(b"replacement"), "new.mp4"),
    })
    assert response.status_code == 200
    assert not response.json["has_transcript"]
    assert response.json["srt_download_url"] is None
    assert response.json["status"] == "uploaded"
    assert not old_source.exists()
    assert not output.exists()
    with app.app_context():
        assert TranscriptWordRecord.query.filter_by(project_id=project_id).count() == 0
        assert SubtitleSegment.query.filter_by(project_id=project_id).count() == 0


def test_preflights_only_require_tools_used_by_stage(app, monkeypatch):
    ok = lambda *a, **k: diagnostics.DiagnosticCheck("test", "pass", "ready")
    def unexpected(*args, **kwargs):
        pytest.fail("Preflight checked an unrelated dependency")
    for name in ["check_database", "check_redis", "check_storage", "check_ffmpeg", "check_transcription_provider"]:
        monkeypatch.setattr(diagnostics, name, ok)
    monkeypatch.setattr(diagnostics, "check_translation_provider", unexpected)
    with app.app_context():
        project = db.session.get(Project, app.config["PROJECT_ID"])
        assert diagnostics.run_job_preflight("transcribe", project, include_worker=False).ready
        db.session.add(TranscriptWordRecord(project_id=project.id, word_index=0, raw_text="Hello", start_time=0, end_time=1))
        db.session.commit()
        monkeypatch.setattr(diagnostics, "check_translation_provider", ok)
        monkeypatch.setattr(diagnostics, "check_ffmpeg", unexpected)
        monkeypatch.setattr(diagnostics, "check_transcription_provider", unexpected)
        monkeypatch.setattr(diagnostics, "check_project_file", unexpected)
        assert diagnostics.run_job_preflight("translate", project, include_worker=False).ready
