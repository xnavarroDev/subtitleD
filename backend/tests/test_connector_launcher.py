import argparse
import importlib.util
from pathlib import Path
import sys
import json
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location("local_connector_launcher", Path(__file__).resolve().parents[2] / "local_connector.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.mark.parametrize("origin", [
    "http://public.example", "https://example.com/path", "https://user:pass@example.com",
    "https://example.com?token=x", "https://example.com#part", "https://example.com\nINJECT=value",
])
def test_launcher_rejects_unsafe_or_inexact_origins(origin):
    with pytest.raises(argparse.ArgumentTypeError):
        launcher.trusted_origin(origin)


def test_launcher_normalizes_https_and_allows_local_development():
    assert launcher.trusted_origin("https://subtitles.example/") == "https://subtitles.example"
    assert launcher.trusted_origin("http://localhost:5173") == "http://localhost:5173"


def test_launcher_generates_stable_pairing_code_and_preserves_data_on_stop(tmp_path, monkeypatch, capsys):
    config = tmp_path / ".env.connector"
    monkeypatch.setattr(launcher, "CONFIG", config)
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(launcher, "check_prerequisites", lambda **kwargs: [])
    monkeypatch.setattr(launcher, "check_port", lambda values: None)
    monkeypatch.setattr(launcher, "wait_for_connector", lambda values: None)
    monkeypatch.setattr(launcher, "run_capture", lambda command: SimpleNamespace(returncode=1))
    monkeypatch.setattr(launcher, "backend_fingerprint", lambda: "source-version")
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)
    commands = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda cmd, **kwargs: (commands.append(cmd) or SimpleNamespace(returncode=0)))
    monkeypatch.setattr(sys, "argv", ["local_connector.py", "start", "--origin", "https://subtitles.example"])
    launcher.main()
    original = config.read_text()
    token = dict(line.split("=", 1) for line in original.splitlines())["CONNECTOR_TOKEN"]
    assert len(token) >= 32
    assert token in capsys.readouterr().out
    assert commands[0][-3:] == ["up", "-d", "--build"]
    monkeypatch.setattr(sys, "argv", ["local_connector.py", "start"])
    launcher.main()
    assert config.read_text() == original
    monkeypatch.setattr(sys, "argv", ["local_connector.py", "stop"])
    launcher.main()
    assert commands[-1][-1] == "down"
    assert "--volumes" not in commands[-1]
    assert config.read_text() == original


@pytest.mark.parametrize("result,message", [
    (SimpleNamespace(returncode=1, stdout=""), "not responding"),
    (SimpleNamespace(returncode=0, stdout="windows"), "Linux containers"),
])
def test_docker_engine_problems_have_actionable_errors(monkeypatch, result, message):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(launcher, "run_capture", lambda command: SimpleNamespace(returncode=0) if command[1] == "compose" else result)
    with pytest.raises(launcher.SetupError, match=message):
        launcher.check_prerequisites()


def test_missing_docker_does_not_attempt_startup(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    with pytest.raises(launcher.SetupError, match="Install Docker Desktop"):
        launcher.check_prerequisites()


def test_website_setup_imports_only_allowed_settings(tmp_path):
    path = tmp_path / "setup.json"
    path.write_text(json.dumps({"version": 1, "origin": "https://subtitles.example", "whisper_model": "base", "connector_port": 5001, "kobold_port": 5003, "CONNECTOR_TOKEN": "attacker-code", "command": "ignored"}))
    values = launcher.import_setup(path)
    assert values == {
        "CORS_ORIGINS": "https://subtitles.example", "WHISPER_MODEL_SIZE": "base",
        "CONNECTOR_PORT": "5001", "HY_MT_BASE_URL": "http://host.docker.internal:5003/v1",
    }


@pytest.mark.parametrize("data", [
    {"version": 2}, {"version": 1, "origin": "http://public.example"},
    {"version": 1, "origin": 42}, {"version": 1, "origin": "https://example.com", "connector_port": 5000.5},
    {"version": 1, "origin": "https://example.com", "whisper_model": "unknown"},
])
def test_invalid_setup_file_is_rejected(tmp_path, data):
    path = tmp_path / "setup.json"
    path.write_text(json.dumps(data))
    with pytest.raises(launcher.SetupError):
        launcher.import_setup(path)


def test_guided_setup_uses_defaults_and_preserves_pairing(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda question: "")
    values = launcher.guided_setup({"CONNECTOR_TOKEN": "existing"})
    assert values["CORS_ORIGINS"] == "http://localhost:5173"
    assert values["WHISPER_MODEL_SIZE"] == "small"
    assert values["CONNECTOR_TOKEN"] == "existing"


def test_port_conflict_needs_existing_authenticated_connector(monkeypatch):
    class BusyPort:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, address): raise OSError("busy")
    monkeypatch.setattr(launcher.socket, "socket", BusyPort)
    monkeypatch.setattr(launcher, "session_ready", lambda values: False)
    with pytest.raises(launcher.SetupError, match="--port 5001"):
        launcher.check_port({})
    monkeypatch.setattr(launcher, "session_ready", lambda values: True)
    launcher.check_port({})


def test_startup_timeout_has_recovery_instructions(monkeypatch):
    monkeypatch.setattr(launcher, "session_ready", lambda values: False)
    with pytest.raises(launcher.SetupError, match="logs"):
        launcher.wait_for_connector({}, timeout=0)


def test_automatic_port_skips_busy_ports_and_translator_then_reuses_own_service(monkeypatch):
    attempted = []
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def setsockopt(self, *args): pass
        def bind(self, address):
            self.port = address[1]
            attempted.append(self.port)
            if self.port in {5000, 5001}: raise OSError("busy")
        def getsockname(self): return ("127.0.0.1", self.port)
    monkeypatch.setattr(launcher.socket, "socket", Probe)
    monkeypatch.setattr(launcher, "session_ready", lambda values: False)
    values = {"CONNECTOR_PORT": "5000", "HY_MT_BASE_URL": "http://host.docker.internal:5003/v1"}
    assert launcher.choose_port(values) == 5004
    assert attempted == [5000, 5001, 5004]
    monkeypatch.setattr(launcher, "session_ready", lambda values: True)
    assert launcher.choose_port(values) == 5000


def test_companion_port_and_project_are_persisted_for_pairing_and_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "CONFIG", tmp_path / ".env.connector")
    monkeypatch.setattr(launcher, "check_prerequisites", lambda **kw: [])
    monkeypatch.setattr(launcher, "choose_port", lambda values: 5004)
    monkeypatch.setattr(launcher, "wait_for_connector", lambda values: None)
    monkeypatch.setattr(launcher, "backend_fingerprint", lambda: "source")
    monkeypatch.setattr(launcher, "run_capture", lambda cmd: SimpleNamespace(returncode=0))
    commands = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, **kw: commands.append(command) or SimpleNamespace(returncode=0))
    launcher.main(["start", "--origin", "https://example.com", "--auto-port", "--project-name", "subtitled-companion", "--no-browser", "--quiet-pairing"])
    values = launcher.read_config()
    assert values["CONNECTOR_PORT"] == "5004"
    assert launcher.connector_address(values) == "http://localhost:5004/api"
    assert commands[-1][commands[-1].index("--project-name") + 1] == "subtitled-companion"
    launcher.main(["stop"])
    assert commands[-1][commands[-1].index("--project-name") + 1] == "subtitled-companion"
    assert commands[-1][-1] == "down"


def test_existing_image_is_rebuilt_after_code_changes_and_failed_build_does_not_record_version(tmp_path, monkeypatch):
    config = tmp_path / ".env.connector"
    monkeypatch.setattr(launcher, "CONFIG", config)
    monkeypatch.setattr(launcher, "check_prerequisites", lambda **kwargs: [])
    monkeypatch.setattr(launcher, "check_port", lambda values: None)
    monkeypatch.setattr(launcher, "wait_for_connector", lambda values: None)
    monkeypatch.setattr(launcher, "run_capture", lambda command: SimpleNamespace(returncode=0))
    monkeypatch.setattr(launcher, "backend_fingerprint", lambda: "old-source")
    commands = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, **kwargs: (commands.append(command) or SimpleNamespace(returncode=0)))
    launcher.main(["start", "--origin", "https://example.com", "--no-browser"])
    assert "--build" in commands[-1]
    launcher.main(["start", "--no-browser"])
    assert "--build" not in commands[-1]
    monkeypatch.setattr(launcher, "backend_fingerprint", lambda: "new-source")
    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    with pytest.raises(SystemExit):
        launcher.main(["start", "--no-browser"])
    assert launcher.read_config()["CONNECTOR_BUILD_FINGERPRINT"] == "old-source"


def test_node_is_only_needed_for_local_website_mode(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "docker" if name == "docker" else None)
    monkeypatch.setattr(launcher, "run_capture", lambda command: SimpleNamespace(returncode=0, stdout="linux"))
    assert launcher.check_prerequisites(local_frontend=False)
    with pytest.raises(launcher.SetupError, match="Node.js"):
        launcher.check_prerequisites(local_frontend=True)


def test_release_image_is_pinned_and_downloaded_without_local_build(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "CONFIG", tmp_path / ".env.connector")
    monkeypatch.setattr(launcher, "check_prerequisites", lambda **kw: [])
    monkeypatch.setattr(launcher, "check_port", lambda values: None)
    monkeypatch.setattr(launcher, "wait_for_connector", lambda values: None)
    monkeypatch.setattr(launcher, "backend_fingerprint", lambda: "source")
    commands = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, **kw: commands.append(command) or SimpleNamespace(returncode=0))
    image = "ghcr.io/example/subtitled@sha256:" + "a" * 64
    launcher.write_config({"CONNECTOR_IMAGE": image})
    launcher.main(["start", "--origin", "https://example.com", "--no-browser", "--quiet-pairing"])
    assert commands[-1][-5:] == ["up", "-d", "--no-build", "--pull", "missing"]
    assert launcher.read_config()["CONNECTOR_TOKEN"] not in capsys.readouterr().out
    launcher.write_config({"CONNECTOR_IMAGE": "untrusted:latest"})
    with pytest.raises(SystemExit):
        launcher.main(["start", "--origin", "https://example.com", "--no-browser"])


def test_closing_local_website_terminates_its_child_process(tmp_path, monkeypatch):
    vite = tmp_path / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    vite.parent.mkdir(parents=True)
    vite.write_text("// test placeholder")
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "node")
    terminated = []
    class Child:
        def poll(self): return None
        def wait(self, timeout=None):
            if timeout is None:
                raise KeyboardInterrupt()
            return 0
        def terminate(self): terminated.append(True)
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: Child())
    monkeypatch.setattr(launcher, "urlopen", lambda *args, **kwargs: Response())
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)
    with pytest.raises(KeyboardInterrupt):
        launcher.start_local_website({"CORS_ORIGINS": "http://localhost:5173"})
    assert terminated == [True]
