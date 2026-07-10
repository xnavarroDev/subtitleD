from pathlib import Path

import pytest

from app import create_app
from app import diagnostics as diagnostics_module
from app import routes
from app import tasks
from app.diagnostics import (
    DiagnosticCheck,
    DiagnosticReport,
    PreflightError,
    check_ffmpeg,
    check_storage,
)
from app.extensions import db
from app.models import Project, ProjectStatus, SubtitleSegment


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    CORS_ORIGINS = ["http://localhost:5173"]
    CREATE_TABLES = True
    DIAGNOSTICS_TIMEOUT_SECONDS = 1
    DIAGNOSTICS_DEEP_CACHE_TTL_SECONDS = 300
    WORKER_PING_TIMEOUT_SECONDS = 1
    MIN_FREE_STORAGE_BYTES = 1


@pytest.fixture()
def app(tmp_path):
    class TestConfigWithStorage(TestConfig):
        STORAGE_DIR = tmp_path / "storage"
        WHISPER_MODEL_DIR = STORAGE_DIR / "models"

    app = create_app(TestConfigWithStorage)
    with app.app_context():
        diagnostics_module.clear_diagnostics_cache()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_diagnostic_report_is_unavailable_when_any_check_fails():
    report = DiagnosticReport(
        mode="quick",
        checks=(
            DiagnosticCheck("storage", "pass", "ready"),
            DiagnosticCheck("worker", "fail", "offline"),
        ),
    )

    assert report.ready is False
    assert report.status == "unavailable"
    assert report.to_dict()["checks"][1]["name"] == "worker"


def test_diagnostic_report_can_hide_internal_details():
    report = DiagnosticReport(
        mode="quick",
        checks=(
            DiagnosticCheck(
                "worker",
                "pass",
                "ready",
                {"workers": ["celery@internal-host"]},
            ),
        ),
    )

    payload = report.to_dict(include_details=False)

    assert "details" not in payload["checks"][0]


def test_worker_check_uses_redis_heartbeat_without_control_ping(app, monkeypatch):
    class FakeRedis:
        def scan_iter(self, match, count):
            assert match == "subtitled:workers:heartbeat:*"
            assert count == 100
            return iter([b"subtitled:workers:heartbeat:worker-1"])

        def close(self):
            pass

    monkeypatch.setattr(
        diagnostics_module.Redis,
        "from_url",
        lambda *args, **kwargs: FakeRedis(),
    )

    def unexpected_ping(**_kwargs):
        raise AssertionError("control ping should not run when a heartbeat exists")

    monkeypatch.setattr(
        diagnostics_module.celery_app.control,
        "ping",
        unexpected_ping,
    )

    with app.app_context():
        result = diagnostics_module.check_worker()

    assert result.status == "pass"
    assert result.details == {"source": "heartbeat", "worker_count": 1}


def test_worker_check_falls_back_to_control_ping(app, monkeypatch):
    class FakeRedis:
        def scan_iter(self, match, count):
            return iter([])

        def close(self):
            pass

    monkeypatch.setattr(
        diagnostics_module.Redis,
        "from_url",
        lambda *args, **kwargs: FakeRedis(),
    )
    monkeypatch.setattr(
        diagnostics_module.celery_app.control,
        "ping",
        lambda timeout: [{"celery@test-worker": {"ok": "pong"}}],
    )

    with app.app_context():
        result = diagnostics_module.check_worker()

    assert result.status == "pass"
    assert result.details["source"] == "control_ping"


def test_storage_check_confirms_required_directories_are_writable(app):
    with app.app_context():
        result = check_storage()

    assert result.status == "pass"
    assert result.details["free_bytes"] > 0


def test_ffmpeg_check_reports_missing_binary(app, monkeypatch):
    monkeypatch.setattr(diagnostics_module.shutil, "which", lambda _name: None)

    with app.app_context():
        result = check_ffmpeg()

    assert result.status == "fail"
    assert "not installed" in result.message


def test_diagnostics_endpoint_returns_report_and_status(client, monkeypatch):
    report = DiagnosticReport(
        mode="deep",
        checks=(DiagnosticCheck("worker", "fail", "No worker."),),
    )
    calls = []

    def fake_run_system_diagnostics(deep=False, refresh=False):
        calls.append((deep, refresh))
        return report

    monkeypatch.setattr(routes, "run_system_diagnostics", fake_run_system_diagnostics)

    response = client.get("/api/diagnostics?deep=true&refresh=1")

    assert response.status_code == 503
    assert response.json["status"] == "unavailable"
    assert response.json["mode"] == "deep"
    assert "details" not in response.json["checks"][0]
    assert calls == [(True, True)]


def test_diagnostics_cli_returns_nonzero_for_failed_report(app, monkeypatch):
    report = DiagnosticReport(
        mode="quick",
        checks=(DiagnosticCheck("redis", "fail", "Redis unavailable."),),
    )
    monkeypatch.setattr(
        diagnostics_module,
        "run_system_diagnostics",
        lambda deep=False, refresh=False, load_models=False: report,
    )

    result = app.test_cli_runner().invoke(args=["diagnostics", "--json-output"])

    assert result.exit_code == 1
    assert '"status": "unavailable"' in result.output


def test_deep_cache_only_reuses_transcription_check(app, monkeypatch):
    calls = {"database": 0, "transcription": 0}

    def database_check():
        calls["database"] += 1
        return DiagnosticCheck("database", "pass", "ready")

    def transcription_check(deep=False, load_models=False):
        calls["transcription"] += 1
        return DiagnosticCheck("transcription", "pass", "ready")

    monkeypatch.setattr(diagnostics_module, "check_database", database_check)
    monkeypatch.setattr(
        diagnostics_module,
        "check_transcription_provider",
        transcription_check,
    )
    monkeypatch.setattr(
        diagnostics_module,
        "check_redis",
        lambda: DiagnosticCheck("redis", "pass", "ready"),
    )
    monkeypatch.setattr(
        diagnostics_module,
        "check_worker",
        lambda: DiagnosticCheck("worker", "pass", "ready"),
    )
    monkeypatch.setattr(
        diagnostics_module,
        "check_storage",
        lambda: DiagnosticCheck("storage", "pass", "ready"),
    )
    monkeypatch.setattr(
        diagnostics_module,
        "check_ffmpeg",
        lambda require_subtitles=False: DiagnosticCheck("ffmpeg", "pass", "ready"),
    )
    monkeypatch.setattr(
        diagnostics_module,
        "check_translation_provider",
        lambda source_language=None, target_language=None: DiagnosticCheck(
            "translation", "pass", "ready"
        ),
    )

    with app.app_context():
        first = diagnostics_module.run_system_diagnostics(deep=True, refresh=True)
        second = diagnostics_module.run_system_diagnostics(deep=True)

    assert first.cached is False
    assert second.cached is True
    assert calls == {"database": 2, "transcription": 1}


def test_process_endpoint_blocks_queueing_when_preflight_fails(client, app, monkeypatch):
    with app.app_context():
        source = Path(app.config["STORAGE_DIR"]) / "uploads" / "source.mp4"
        source.write_bytes(b"video")
        project = Project(
            title="Demo",
            source_language="English",
            target_language="Spanish",
            source_video_path=str(source),
            status=ProjectStatus.UPLOADED,
        )
        db.session.add(project)
        db.session.commit()
        project_id = project.id

    report = DiagnosticReport(
        mode="process_preflight",
        checks=(DiagnosticCheck("worker", "fail", "No worker responded."),),
    )

    def fail_preflight(*_args, **_kwargs):
        raise PreflightError(report)

    monkeypatch.setattr(routes, "require_job_preflight", fail_preflight)

    response = client.post(f"/api/projects/{project_id}/process")

    assert response.status_code == 503
    assert response.json["diagnostics"]["mode"] == "process_preflight"
    with app.app_context():
        assert db.session.get(Project, project_id).status == ProjectStatus.UPLOADED


def test_process_preflight_uses_project_translation_provider(app, monkeypatch):
    with app.app_context():
        source = Path(app.config["STORAGE_DIR"]) / "uploads" / "source.mp4"
        source.write_bytes(b"video")
        project = Project(
            title="Demo",
            source_language="en",
            target_language="es",
            source_video_path=str(source),
            translation_provider="nllb-ct2",
            status=ProjectStatus.UPLOADED,
        )

        monkeypatch.setattr(
            diagnostics_module,
            "check_database",
            lambda: DiagnosticCheck("database", "pass", "ready"),
        )
        monkeypatch.setattr(
            diagnostics_module,
            "check_redis",
            lambda: DiagnosticCheck("redis", "pass", "ready"),
        )
        monkeypatch.setattr(
            diagnostics_module,
            "check_storage",
            lambda: DiagnosticCheck("storage", "pass", "ready"),
        )
        monkeypatch.setattr(
            diagnostics_module,
            "check_ffmpeg",
            lambda require_subtitles=False: DiagnosticCheck("ffmpeg", "pass", "ready"),
        )
        monkeypatch.setattr(
            diagnostics_module,
            "check_transcription_provider",
            lambda deep=False, diarize=False: DiagnosticCheck("transcription", "pass", "ready"),
        )
        calls = []

        def check_translation_provider(source_language=None, target_language=None, provider_name=None):
            calls.append((source_language, target_language, provider_name))
            return DiagnosticCheck("translation", "pass", "ready")

        monkeypatch.setattr(
            diagnostics_module,
            "check_translation_provider",
            check_translation_provider,
        )

        diagnostics_module.run_job_preflight("process", project, include_worker=False)

    assert calls == [("en", "es", "nllb-ct2")]


def test_render_endpoint_blocks_queueing_when_preflight_fails(client, app, monkeypatch):
    with app.app_context():
        source = Path(app.config["STORAGE_DIR"]) / "uploads" / "source.mp4"
        source.write_bytes(b"video")
        project = Project(
            title="Demo",
            source_language="English",
            target_language="Spanish",
            source_video_path=str(source),
            status=ProjectStatus.PROCESSED,
        )
        db.session.add(project)
        db.session.flush()
        db.session.add(
            SubtitleSegment(
                project_id=project.id,
                start_time=0,
                end_time=1,
                original_text="Hello",
                translated_text="Hola",
                segment_index=0,
            )
        )
        db.session.commit()
        project_id = project.id

    report = DiagnosticReport(
        mode="render_preflight",
        checks=(DiagnosticCheck("ffmpeg", "fail", "FFmpeg unavailable."),),
    )

    def fail_preflight(*_args, **_kwargs):
        raise PreflightError(report)

    monkeypatch.setattr(routes, "require_job_preflight", fail_preflight)

    response = client.post(f"/api/projects/{project_id}/render")

    assert response.status_code == 503
    with app.app_context():
        assert db.session.get(Project, project_id).status == ProjectStatus.PROCESSED


def test_worker_rechecks_preflight_before_processing(app, monkeypatch):
    with app.app_context():
        source = Path(app.config["STORAGE_DIR"]) / "uploads" / "source.mp4"
        source.write_bytes(b"video")
        project = Project(
            title="Demo",
            source_language="English",
            target_language="Spanish",
            source_video_path=str(source),
            status=ProjectStatus.PROCESSING,
        )
        db.session.add(project)
        db.session.commit()
        project_id = project.id

    report = DiagnosticReport(
        mode="process_preflight",
        checks=(DiagnosticCheck("storage", "fail", "Storage unavailable."),),
    )
    calls = []

    def fail_preflight(job_type, project, include_worker=True):
        calls.append((job_type, project.id, include_worker))
        raise PreflightError(report)

    monkeypatch.setattr(tasks, "require_job_preflight", fail_preflight)

    with app.app_context(), pytest.raises(PreflightError):
        tasks.process_video_task.run(project_id)

    assert calls == [("process", project_id, False)]
    with app.app_context():
        failed_project = db.session.get(Project, project_id)
        assert failed_project.status == ProjectStatus.FAILED
        assert failed_project.error_message == "Storage unavailable."
