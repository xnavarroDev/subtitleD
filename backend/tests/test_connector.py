import time

import pytest

from app import create_app
from app import connector
from app.extensions import db
from app.models import Project, SubtitleSegment


TOKEN = "test-pairing-secret-" + "x" * 32
ORIGIN = "https://subtitles.example"


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
        CORS_ORIGINS = [ORIGIN]
        CONNECTOR_MODE = True
        CONNECTOR_TOKEN = TOKEN
        TRANSLATION_PROVIDER = "mock"

    application = create_app(Config)
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


def headers(**extra):
    return {"Origin": ORIGIN, "Authorization": f"Bearer {TOKEN}", **extra}


def test_pairing_required_for_api_and_not_health(app):
    client = app.test_client()
    assert client.get("/health").status_code == 200
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers=headers()).status_code == 200
    bad = client.post("/api/connector/session", headers=headers(Authorization="Bearer wrong"))
    assert bad.status_code == 401
    assert "pairing code" in bad.json["error"]
    result = client.post("/api/connector/session", headers=headers())
    assert result.status_code == 200
    assert result.json["protocol_version"] == 1
    assert result.json["protected"] is True
    assert TOKEN not in result.get_data(as_text=True)
    assert result.headers["Cache-Control"] == "no-store"


def test_untrusted_origin_and_host_are_rejected_even_with_pairing_code(app):
    client = app.test_client()
    assert client.get("/api/projects", headers=headers(Origin="https://attacker.example")).status_code == 403
    assert client.get("/api/projects", headers=headers(Host="attacker.example:5000")).status_code == 403


def test_preflight_allows_trusted_website_without_pairing_header(app):
    response = app.test_client().options("/api/projects", headers={
        "Origin": ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "authorization" in response.headers["Access-Control-Allow-Headers"].lower()


def test_companion_ticket_is_authenticated_origin_bound_and_single_use(app, monkeypatch):
    client = app.test_client()
    assert client.post("/api/connector/pairing-ticket", json={"origin": ORIGIN}).status_code == 401
    assert client.post("/api/connector/pairing-ticket", headers=headers(), json={"origin": "https://other.example"}).status_code == 403
    ticket = client.post("/api/connector/pairing-ticket", headers=headers(), json={"origin": ORIGIN}).json["ticket"]
    assert TOKEN not in ticket
    assert client.post("/api/connector/pair", json={"ticket": ticket}).status_code == 401
    assert client.post("/api/connector/pair", headers={"Origin": "https://evil.example"}, json={"ticket": ticket}).status_code == 403
    paired = client.post("/api/connector/pair", headers={"Origin": ORIGIN}, json={"ticket": ticket})
    assert paired.status_code == 200 and paired.json["code"] == TOKEN
    assert paired.headers["Cache-Control"] == "no-store"
    assert client.post("/api/connector/pair", headers={"Origin": ORIGIN}, json={"ticket": ticket}).status_code == 401
    ticket = client.post("/api/connector/pairing-ticket", headers=headers(), json={"origin": ORIGIN}).json["ticket"]
    now = time.time()
    monkeypatch.setattr(connector.time, "time", lambda: now + 121)
    assert client.post("/api/connector/pair", headers={"Origin": ORIGIN}, json={"ticket": ticket}).status_code == 401


@pytest.mark.parametrize("payload", [[], "text", {"ticket": []}, {"ticket": "x" * 129}, None])
def test_malformed_companion_handoffs_fail_closed(app, payload):
    assert app.test_client().post("/api/connector/pair", headers={"Origin": ORIGIN}, json=payload).status_code == 401


def test_media_ticket_supports_range_requests_but_cannot_read_or_mutate_projects(app, monkeypatch):
    with app.app_context():
        source = app.config["STORAGE_DIR"] / "uploads" / "clip.mp4"
        source.write_bytes(b"0123456789")
        project = Project(title="Private", source_language="en", target_language="es", source_video_path=str(source))
        db.session.add(project)
        db.session.commit()
        project_id = project.id
    client = app.test_client()
    session = client.post("/api/connector/session", headers=headers()).json
    ticket = session["media_token"]
    media = f"/api/projects/{project_id}/media/source?media_token={ticket}"
    assert client.get(media, headers={"Range": "bytes=2-5"}).data == b"2345"
    assert client.get(media, headers={"Range": "bytes=2-5"}).status_code == 206
    assert client.head(media).status_code == 200
    assert client.get(f"/api/projects?media_token={ticket}").status_code == 401
    assert client.delete(f"/api/projects/{project_id}?media_token={ticket}").status_code == 401
    assert client.get(media + "tampered").status_code == 401
    now = time.time()
    monkeypatch.setattr(connector.time, "time", lambda: now + 43201)
    assert client.get(media).status_code == 401


@pytest.mark.parametrize("setting,value", [("CONNECTOR_TOKEN", "short"), ("CORS_ORIGINS", ["*"])])
def test_insecure_connector_configuration_fails_closed(app, setting, value):
    class Invalid:
        pass
    for key, item in app.config.items():
        setattr(Invalid, key, item)
    setattr(Invalid, setting, value)
    with pytest.raises(ValueError):
        create_app(Invalid)
