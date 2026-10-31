from types import SimpleNamespace

import pytest

from app import create_app, providers
from app.diagnostics import DiagnosticCheck
from app.extensions import db


@pytest.mark.parametrize("status,exit_code", [("pass", 0), ("fail", 1)])
def test_model_preparation_is_explicit_and_does_not_require_translation(tmp_path, monkeypatch, status, exit_code):
    class Config:
        TESTING = True
        CREATE_TABLES = True
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        STORAGE_DIR = tmp_path
        CELERY_BROKER_URL = "memory://"
        CELERY_RESULT_BACKEND = "cache+memory://"
        CORS_ORIGINS = ["http://localhost:5173"]
    calls = []
    def prepare(**options):
        calls.append(options)
        return DiagnosticCheck("transcription", status, "Test model preparation")
    monkeypatch.setattr(providers, "get_transcription_provider", lambda: SimpleNamespace(check_ready=prepare))
    app = create_app(Config)
    result = app.test_cli_runner().invoke(args=["prepare-transcription"])
    assert result.exit_code == exit_code
    assert calls == [{"deep": False, "load_models": True, "diarize": False}]
    with app.app_context():
        db.session.remove()
        db.drop_all()
