from types import SimpleNamespace

import pytest

from app import create_app, caption_editing
from app.extensions import db
from app.models import Project, ProjectStatus, SubtitleSegment, TranscriptWordRecord


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
    app = create_app(Config)
    with app.app_context():
        project = Project(title="Conversation", source_language="zh", target_language="en", status="processed")
        db.session.add(project)
        db.session.flush()
        for index, (source, translation) in enumerate([("你不是说", "Didn't you say"), ("他昨天已经走了吗？", "he left yesterday?"), ("他又回来了。", "He came back.")]):
            db.session.add(SubtitleSegment(project_id=project.id, segment_index=index, start_time=index * 3, end_time=index * 3 + 2, original_text=source, translated_text=translation, translation_provider="hy-mt2-kobold"))
        db.session.add(TranscriptWordRecord(project_id=project.id, word_index=0, raw_text="你", start_time=0, end_time=.2))
        db.session.commit()
        app.config["PROJECT_ID"] = project.id
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def rows(app, client):
    return client.get(f"/api/projects/{app.config['PROJECT_ID']}/segments").json


def combine(app, client, selected):
    return client.post(f"/api/projects/{app.config['PROJECT_ID']}/segments/merge", json={"segment_ids": [row["id"] for row in selected], "revisions": {row["id"]: row["updated_at"] for row in selected}})


def test_merge_and_split_restore_exact_timings_and_text_without_changing_transcript(app):
    client = app.test_client()
    original = rows(app, client)
    response = combine(app, client, original[:2])
    assert response.status_code == 200
    merged = response.json[0]
    assert merged["original_text"] == "你不是说 他昨天已经走了吗？"
    assert (merged["start_time"], merged["end_time"]) == (0, 5)
    assert len(response.json) == 2
    response = client.post(f"/api/segments/{merged['id']}/split", json={"revision": merged["updated_at"], "parts": [{"translated_text": part["translated_text"]} for part in merged["merge_parts"]]})
    assert response.status_code == 200
    fields = ["original_text", "translated_text", "start_time", "end_time", "segment_index"]
    assert [[row[field] for field in fields] for row in response.json] == [[row[field] for field in fields] for row in original]
    with app.app_context():
        assert TranscriptWordRecord.query.one().raw_text == "你"


def test_nonadjacent_cross_project_stale_and_busy_edits_are_rejected(app):
    client = app.test_client()
    original = rows(app, client)
    assert combine(app, client, original[::2]).status_code == 400
    stale = [dict(row, updated_at="outdated") for row in original[:2]]
    assert combine(app, client, stale).status_code == 409
    assert len(rows(app, client)) == 3
    with app.app_context():
        db.session.get(Project, app.config["PROJECT_ID"]).status = ProjectStatus.PROCESSING
        db.session.commit()
    assert combine(app, client, original[:2]).status_code == 409


def test_retranslation_is_preview_with_conversation_context_and_fallback_provenance(app, monkeypatch):
    client = app.test_client()
    merged = combine(app, client, rows(app, client)[:2]).json[0]
    calls = []
    class Provider:
        def check_ready(self, *args): return SimpleNamespace(status="warn")
        def translate_with_context(self, *args):
            calls.append(args)
            return SimpleNamespace(text="Didn't you say he had already left yesterday?", provider="nllb-ct2", model="test-model", warning="HY-MT2 unavailable; NLLB used")
    monkeypatch.setattr(caption_editing, "get_translation_provider", lambda **kw: Provider())
    result = client.post(f"/api/segments/{merged['id']}/translate")
    assert result.status_code == 200 and result.json["provider"] == "nllb-ct2"
    assert calls[0][0] == merged["original_text"]
    assert calls[0][3] == () and calls[0][4] == ("他又回来了。",)
    assert rows(app, client)[0]["translated_text"] == merged["translated_text"]
    update = client.patch(f"/api/segments/{merged['id']}", json={"revision": merged["updated_at"], "translated_text": result.json["translated_text"], "translation_provenance": result.json})
    assert update.status_code == 200 and update.json["translation_provider"] == "nllb-ct2"
    split = client.post(f"/api/segments/{merged['id']}/split", json={"revision": update.json["updated_at"], "parts": [{"translated_text": "Didn't you say"}, {"translated_text": "he had already left yesterday?"}]})
    assert split.status_code == 200
    assert split.json[1]["translated_text"] == "he had already left yesterday?"
    assert split.json[1]["translation_provider"] == "nllb-ct2"


def test_custom_split_preserves_all_source_and_rejects_invalid_time_or_empty_translation(app):
    client = app.test_client()
    row = rows(app, client)[1]
    endpoint = f"/api/segments/{row['id']}/split"
    parts = [{"original_text": "他昨天", "translated_text": "Yesterday", "start_time": 3, "end_time": 4}, {"original_text": "已经走了吗？", "translated_text": "had he left?", "start_time": 4, "end_time": 5}]
    bad = [dict(parts[0], end_time=float("nan")), parts[1]]
    assert client.post(endpoint, json={"revision": row["updated_at"], "parts": bad}).status_code == 400
    assert client.post(endpoint, json={"revision": row["updated_at"], "parts": [dict(parts[0], original_text="lost text"), parts[1]]}).status_code == 400
    assert client.post(endpoint, json={"revision": row["updated_at"], "parts": [dict(parts[0], translated_text=""), parts[1]]}).status_code == 400
    result = client.post(endpoint, json={"revision": row["updated_at"], "parts": parts})
    assert result.status_code == 200
    assert len(result.json) == 4 and result.json[1]["timing_quality"] == "estimated"
