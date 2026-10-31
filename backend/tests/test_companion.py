import argparse
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import companion


@pytest.mark.parametrize("link", [
    "subtitled://connect?origin=http%3A%2F%2Fpublic.example",
    "subtitled://connect?origin=https://example.com/path",
    "subtitled://connect?origin=https://example.com&origin=https://evil.example",
    "subtitled://connect?origin=https://example.com&command=stop",
    "subtitled://stop?origin=https://example.com",
    "subtitled://connect?origin=https://example.com#ignored",
])
def test_handoff_cannot_supply_commands_or_unsafe_origins(link):
    with pytest.raises((ValueError, argparse.ArgumentTypeError)):
        companion.parse_link(link)


def test_link_and_worker_arguments_are_separate():
    assert companion.parse_link("subtitled://connect?origin=https%3A%2F%2Fsubtitles.example") == "https://subtitles.example"
    with pytest.raises(SystemExit):
        companion.main(["--url", "subtitled://connect?origin=https://example.com", "--worker", "stop"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file locking")
def test_second_launch_reopens_existing_window_without_second_gui(tmp_path, monkeypatch):
    monkeypatch.setattr(companion, "configure_runtime", lambda *args: None)
    windows = []
    class Window:
        def __init__(self, *args): windows.append(True)
        def mainloop(self): companion.main(["--home", str(tmp_path)])
    monkeypatch.setattr(companion, "Companion", Window)
    companion.main(["--home", str(tmp_path)])
    assert len(windows) == 1
    assert [json.loads(path.read_text()) for path in (tmp_path / "inbox").glob("*.json")] == [{"show": True}]


def test_packaged_updates_preserve_user_data_and_config(tmp_path, monkeypatch):
    bundle, home = tmp_path / "bundle", tmp_path / "home"
    bundle.mkdir()
    home.mkdir()
    (bundle / "docker-compose.local.yml").write_text("updated runtime")
    (bundle / "manifest.json").write_text(json.dumps({"files": ["docker-compose.local.yml"]}))
    (home / ".env.connector").write_text("CONNECTOR_TOKEN=keep-this-secret\nCORS_ORIGINS=https://example.com\n")
    storage = home / "runtime" / "backend" / "storage"
    storage.mkdir(parents=True)
    (storage / "project.mp4").write_bytes(b"private video")
    for name in ["ROOT", "CONFIG", "SETUP_FILE"]:
        monkeypatch.setattr(companion.launcher, name, getattr(companion.launcher, name))
    companion.configure_runtime(home, bundle)
    assert (home / "runtime" / "docker-compose.local.yml").read_text() == "updated runtime"
    assert (storage / "project.mp4").read_bytes() == b"private video"
    assert companion.launcher.read_config()["CONNECTOR_TOKEN"] == "keep-this-secret"


def test_build_manifest_excludes_user_secrets_models_and_videos(tmp_path):
    spec = importlib.util.spec_from_file_location("build_companion", ROOT / "packaging" / "build_companion.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    build.stage_runtime(tmp_path)
    names = json.loads((tmp_path / "manifest.json").read_text())["files"]
    assert "backend/app/connector.py" in names
    assert "backend/Dockerfile" in names
    assert not any("storage" in name or ".env" in name or "tests/" in name for name in names)


def test_connection_link_uses_one_time_ticket_not_long_lived_secret(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"ticket":"one-time-ticket"}'
    requests = []
    monkeypatch.setattr(companion, "urlopen", lambda request, **kw: requests.append(request) or Response())
    link = companion.connection_url({"CORS_ORIGINS": "https://subtitles.example", "CONNECTOR_TOKEN": "private-secret"})
    assert link.startswith("https://subtitles.example/#")
    assert "one-time-ticket" in link and "private-secret" not in link
    assert requests[0].get_header("Authorization") == "Bearer private-secret"
