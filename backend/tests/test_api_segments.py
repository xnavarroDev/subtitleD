from pathlib import Path

import pytest

from app import create_app
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
    TRANSLATION_PROVIDER = "mock"


@pytest.fixture()
def app(tmp_path):
    class TestConfigWithStorage(TestConfig):
        STORAGE_DIR = tmp_path / "storage"

    app = create_app(TestConfigWithStorage)
    with app.app_context():
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_project_serializer_includes_speaker_hints(app):
    with app.app_context():
        project = Project(
            title="Demo",
            source_language="English",
            target_language="Spanish",
            min_speakers=2,
            max_speakers=3,
            status=ProjectStatus.CREATED,
        )

        assert project.to_dict()["min_speakers"] == 2
        assert project.to_dict()["max_speakers"] == 3


def test_segment_serializer_includes_speaker_label_and_confidence(app):
    with app.app_context():
        segment = SubtitleSegment(
            project_id="project-id",
            start_time=0,
            end_time=1,
            original_text="Hello",
            translated_text="Hola",
            speaker_label="SPEAKER_00",
            transcription_confidence=0.87,
            timing_quality="estimated",
            translation_provider="nllb-ct2",
            translation_model="facebook/nllb-200-distilled-600M",
            source_reconstruction_method="speaker_fragment_merge",
            source_was_reconstructed=True,
            translation_unit_id="u000001-000004",
            translation_confidence_warning="Review source",
            segment_index=0,
        )

        assert segment.to_dict()["speaker_label"] == "SPEAKER_00"
        assert segment.to_dict()["transcription_confidence"] == 0.87
        assert segment.to_dict()["timing_quality"] == "estimated"
        assert segment.to_dict()["translation_provider"] == "nllb-ct2"
        assert segment.to_dict()["translation_model"] == "facebook/nllb-200-distilled-600M"
        assert segment.to_dict()["source_was_reconstructed"] is True
        assert segment.to_dict()["translation_unit_id"] == "u000001-000004"
        assert segment.to_dict()["translation_confidence_warning"] == "Review source"


def test_project_serializer_includes_translation_progress(app):
    with app.app_context():
        project = Project(
            title="Demo", source_language="en", target_language="es",
            status=ProjectStatus.PROCESSING, processing_stage="segmenting_and_translating",
            translation_completed_words=12, translation_total_words=30,
        )

        payload = project.to_dict()

        assert payload["processing_stage"] == "segmenting_and_translating"
        assert payload["translation_progress"] == {"completed": 12, "total": 30}


def test_create_project_accepts_optional_speaker_hints(client):
    response = client.post(
        "/api/projects",
        json={
            "title": "Demo",
            "source_language": "English",
            "target_language": "Spanish",
            "min_speakers": 2,
            "max_speakers": 3,
        },
    )

    assert response.status_code == 201
    assert response.json["min_speakers"] == 2
    assert response.json["max_speakers"] == 3


def test_create_project_accepts_glossary(client):
    response = client.post("/api/projects", json={
        "title": "Names", "source_language": "en", "target_language": "es",
        "glossary": "Alonzo\nSubtitleD",
    })

    assert response.status_code == 201
    assert response.json["glossary"] == "Alonzo\nSubtitleD"


def test_create_project_defaults_expensive_features_off_and_accepts_opt_in(client):
    default = client.post("/api/projects", json={
        "title": "Fast", "source_language": "en", "target_language": "es",
    })
    enabled = client.post("/api/projects", json={
        "title": "Detailed", "source_language": "en", "target_language": "es",
        "detect_speakers": True,
        "smooth_speaker_fragments": True,
    })

    assert default.status_code == 201
    assert default.json["detect_speakers"] is False
    assert default.json["smooth_speaker_fragments"] is False
    assert enabled.json["detect_speakers"] is True
    assert enabled.json["smooth_speaker_fragments"] is True


def test_create_project_rejects_invalid_speaker_hint_range(client):
    response = client.post(
        "/api/projects",
        json={
            "title": "Demo",
            "source_language": "English",
            "target_language": "Spanish",
            "min_speakers": 4,
            "max_speakers": 2,
        },
    )

    assert response.status_code == 400
    assert "min_speakers" in response.json["error"]


def test_get_project_includes_language_display_names(client):
    created = client.post(
        "/api/projects",
        json={
            "title": "Named languages",
            "source_language": "en",
            "target_language": "es",
        },
    )

    response = client.get(f"/api/projects/{created.json['id']}")

    assert response.status_code == 200
    assert response.json["source_language_name"] == "English"
    assert response.json["target_language_name"] == "Spanish"


def test_patch_segment_updates_speaker_label(client, app):
    with app.app_context():
        project = Project(
            title="Demo",
            source_language="English",
            target_language="Spanish",
            status=ProjectStatus.PROCESSED,
        )
        db.session.add(project)
        db.session.flush()
        segment = SubtitleSegment(
            project_id=project.id,
            start_time=0,
            end_time=1,
            original_text="Hello",
            translated_text="Hola",
            segment_index=0,
        )
        db.session.add(segment)
        db.session.commit()
        segment_id = segment.id

    response = client.patch(
        f"/api/segments/{segment_id}",
        json={"speaker_label": "SPEAKER_01"},
    )

    assert response.status_code == 200
    assert response.json["speaker_label"] == "SPEAKER_01"


def test_delete_project_removes_record_segments_and_artifacts(client, app, tmp_path):
    with app.app_context():
        storage_dir = Path(app.config["STORAGE_DIR"])
        upload_path = storage_dir / "uploads" / "video.mp4"
        audio_path = storage_dir / "audio" / "audio.wav"
        upload_path.write_bytes(b"video")
        audio_path.write_bytes(b"audio")

        project = Project(
            title="Delete me",
            source_language="English",
            target_language="Spanish",
            source_video_path=str(upload_path),
            extracted_audio_path=str(audio_path),
            status=ProjectStatus.PROCESSED,
        )
        db.session.add(project)
        db.session.flush()
        segment = SubtitleSegment(
            project_id=project.id,
            start_time=0,
            end_time=1,
            original_text="Hello",
            translated_text="Hola",
            segment_index=0,
        )
        db.session.add(segment)
        db.session.commit()
        project_id = project.id
        segment_id = segment.id

    response = client.delete(f"/api/projects/{project_id}")

    assert response.status_code == 204
    assert not upload_path.exists()
    assert not audio_path.exists()
    with app.app_context():
        assert db.session.get(Project, project_id) is None
        assert db.session.get(SubtitleSegment, segment_id) is None
