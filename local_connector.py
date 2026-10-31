"""Guided local setup using only Python's standard library."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import webbrowser


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / ".env.connector"
SETUP_FILE = ROOT / "subtitled-setup.json"
DEFAULT_ORIGIN = "http://localhost:5173"
MODELS = {"base", "small", "medium", "large-v3"}


class SetupError(RuntimeError):
    pass


def trusted_origin(value):
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError("Website address must be text.")
    try:
        parsed = urlsplit(value)
        parsed.port  # Reject invalid or out-of-range ports.
        valid = (
            parsed.scheme in {"https", "http"} and parsed.hostname
            and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
            and parsed.path in {"", "/"}
            and (parsed.scheme == "https" or parsed.hostname in {"localhost", "127.0.0.1", "::1"})
            and not any(char in value for char in "\r\n,$#'\"\\ ")
            and not any(char.isspace() for char in value)
        )
    except ValueError:
        valid = False
    if not valid:
        raise argparse.ArgumentTypeError("Use the website's HTTPS origin, for example https://subtitles.example (no page path).")
    return f"{parsed.scheme}://{parsed.netloc}"


def port_number(value):
    if not re.fullmatch(r"[0-9]+", str(value)):
        raise argparse.ArgumentTypeError("Port must be a whole number between 1024 and 65535.")
    try:
        port = int(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Port must be a number between 1024 and 65535.") from None
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 1024 and 65535.")
    return port


def read_config():
    if not CONFIG.exists():
        return {}
    values = {}
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise SetupError("The .env.connector file has an invalid line. Use KEY=value entries.")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise SetupError("The .env.connector file contains an invalid setting name.")
        values[key] = value
    return values


def import_setup(path):
    try:
        if path.stat().st_size > 16384:
            raise ValueError("Setup file is too large")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Unsupported setup file version")
        model = data.get("whisper_model", "small")
        if model not in MODELS:
            raise ValueError("Unsupported WhisperX model")
        return {
            "CORS_ORIGINS": trusted_origin(data["origin"]),
            "CONNECTOR_PORT": str(port_number(data.get("connector_port", 5000))),
            "WHISPER_MODEL_SIZE": model,
            "HY_MT_BASE_URL": f"http://host.docker.internal:{port_number(data.get('kobold_port', 5002))}/v1",
        }
    except (OSError, ValueError, KeyError, TypeError, argparse.ArgumentTypeError) as exc:
        raise SetupError(f"Could not read the setup file: {exc}") from exc


def compose():
    project = read_config().get("CONNECTOR_PROJECT_NAME", "subtitled-local")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
        raise SetupError("Invalid local processing project name.")
    return ["docker", "compose", "--project-name", project, "--env-file", str(CONFIG), "-f", str(ROOT / "docker-compose.local.yml")]


def backend_fingerprint():
    digest = hashlib.sha256()
    paths = list((ROOT / "backend" / "app").rglob("*.py"))
    paths.extend(ROOT / "backend" / name for name in ["Dockerfile", "requirements.txt", "run.py", "celery_worker.py"])
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_config(values):
    CONFIG.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")


def run_capture(command):
    try:
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
                              **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f"Could not run {command[0]}. Check that it is installed and responding.") from exc


def check_prerequisites(local_frontend=False):
    checks = []
    if not shutil.which("docker"):
        raise SetupError("Docker is missing. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and start it with Linux containers.")
    if run_capture(["docker", "compose", "version"]).returncode:
        raise SetupError("Docker Compose is unavailable. Update Docker Desktop, then try again.")
    engine = run_capture(["docker", "info", "--format", "{{.OSType}}"])
    if engine.returncode:
        raise SetupError("Docker is installed but its engine is not responding. Open Docker Desktop, wait until it is running, and retry.")
    if engine.stdout.strip() != "linux":
        raise SetupError("Switch Docker Desktop to Linux containers before starting SubtitleD.")
    checks.append("Docker and Linux containers are ready.")
    if shutil.disk_usage(ROOT).free < 10 * 1024 ** 3:
        checks.append("Warning: less than 10 GB of free space. Dependencies, models, and video copies may need more room.")
    else:
        checks.append("At least 10 GB of free space is available; long videos and larger models need more.")
    if local_frontend:
        if not shutil.which("node") or not (shutil.which("npm.cmd") or shutil.which("npm")):
            raise SetupError("Local website mode needs Node.js 20 or later: https://nodejs.org/en/download . Hosted website mode does not need Node.js.")
        version = run_capture(["node", "--version"]).stdout.strip().lstrip("v")
        if not version or not version.split(".")[0].isdigit() or int(version.split(".")[0]) < 20:
            raise SetupError("Update Node.js to version 20 or later for local website mode.")
        checks.append("Node.js is ready for the local website.")
    return checks


def connector_address(values):
    return f"http://localhost:{port_number(values.get('CONNECTOR_PORT', 5000))}/api"


def session_ready(values):
    request = Request(
        connector_address(values) + "/connector/session", data=b"",
        headers={"Authorization": f"Bearer {values['CONNECTOR_TOKEN']}"}, method="POST",
    )
    try:
        with urlopen(request, timeout=3) as response:
            result = json.load(response)
        return isinstance(result, dict) and result.get("protocol_version") == 1 and result.get("protected") is True
    except (OSError, ValueError, URLError):
        return False


def check_port(values):
    port = port_number(values.get("CONNECTOR_PORT", 5000))
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            if not session_ready(values):
                raise SetupError(f"Port {port} is in use by another service. Stop the old backend or run with --port 5001, then use that port on the website.") from None


def choose_port(values):
    """Reuse this connector only after authentication; otherwise find a free port."""
    preferred = port_number(values.get("CONNECTOR_PORT", 5000))
    try:
        check_port(values)
        return preferred
    except SetupError:
        pass
    # Reserve the usual translator port for KoboldCpp and avoid its configured port.
    translator_port = urlsplit(values.get("HY_MT_BASE_URL", "http://host.docker.internal:5002/v1")).port
    for candidate in [port for port in range(5001, 5033) if port not in {preferred, translator_port, 5002}] + [0]:
        with socket.socket() as probe:
            try:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(("127.0.0.1", candidate))
                port = probe.getsockname()[1]
            except OSError:
                continue
        print(f"Port {preferred} is busy. Using local port {port} automatically.", flush=True)
        return port
    raise SetupError("No local port is available. Close an unused local service and retry.")


def wait_for_connector(values, timeout=90):
    deadline = time.monotonic() + timeout
    print("Waiting for the local connector to accept connections...", flush=True)
    while time.monotonic() < deadline:
        if session_ready(values):
            return
        time.sleep(2)
    raise SetupError("The connector has not become ready. Run 'python local_connector.py logs' to inspect startup, then retry. Services were left running.")


def ask(label, default):
    answer = input(f"{label} [{default}]: ").strip()
    return answer or default


def guided_setup(values):
    print("\nSubtitleD setup - your videos and processing stay on this computer.\n")
    print("Use your hosted website address, or keep the default to run the website locally.")
    values["CORS_ORIGINS"] = trusted_origin(ask("Website address", values.get("CORS_ORIGINS", DEFAULT_ORIGIN)))
    print("WhisperX runs on CPU in this first release. 'base' is faster; 'small' is the balanced default.")
    model = ask("Transcription model: base / small / medium / large-v3", values.get("WHISPER_MODEL_SIZE", "small"))
    if model not in MODELS:
        raise SetupError("Choose base, small, medium, or large-v3.")
    values["WHISPER_MODEL_SIZE"] = model
    values["CONNECTOR_PORT"] = str(port_number(ask("Local connector port", values.get("CONNECTOR_PORT", "5000"))))
    print("Translation is optional during setup. Start KoboldCpp separately with an HY-MT2 GGUF when needed.")
    print("KoboldCpp: https://github.com/LostRuins/koboldcpp/releases")
    print("Models: https://huggingface.co/tencent/Hy-MT2-7B-GGUF/tree/main")
    kobold_port = port_number(ask("KoboldCpp port", str(urlsplit(values.get("HY_MT_BASE_URL", "http://host.docker.internal:5002/v1")).port or 5002)))
    values["HY_MT_BASE_URL"] = f"http://host.docker.internal:{kobold_port}/v1"
    return values


def local_website(values):
    parsed = urlsplit(values["CORS_ORIGINS"])
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}


def start_local_website(values):
    frontend = ROOT / "frontend"
    if not (frontend / "node_modules" / "vite" / "bin" / "vite.js").exists():
        print("Installing website dependencies...", flush=True)
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        result = subprocess.run([npm, "ci"], cwd=frontend, check=False)
        if result.returncode:
            raise SetupError("Website dependencies could not be installed. Check your connection and retry.")
    parsed = urlsplit(values["CORS_ORIGINS"])
    port = parsed.port or 80
    log_path = ROOT / "backend" / "storage" / "launcher-frontend.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [shutil.which("node"), "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
            cwd=frontend, stdout=log, stderr=log, **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}),
        )
        try:
            for _ in range(50):
                if process.poll() is not None:
                    raise SetupError("The local website could not start. Its port may be in use. See backend/storage/launcher-frontend.log.")
                try:
                    with urlopen(values["CORS_ORIGINS"], timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(.2)
            else:
                raise SetupError("The local website did not respond. See backend/storage/launcher-frontend.log.")
            webbrowser.open(values["CORS_ORIGINS"])
            print("\nWebsite opened. Keep this launcher open. Press Ctrl+C to close the local website.")
            print("Local processing keeps running; use 'python local_connector.py stop' to stop it.")
            process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Set up and launch SubtitleD on your own device.")
    parser.add_argument("action", nargs="?", default="setup", choices=["setup", "start", "stop", "code", "logs", "doctor", "prepare", "prepare-translation"])
    parser.add_argument("--origin", type=trusted_origin, help="Exact trusted website address.")
    parser.add_argument("--port", type=port_number, help="Local connector port (default 5000).")
    parser.add_argument("--whisper-model", choices=sorted(MODELS))
    parser.add_argument("--setup-file", type=Path, help="Import subtitled-setup.json downloaded from the website.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild local processing after a code update.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser or start a local website.")
    parser.add_argument("--quiet-pairing", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--auto-port", action="store_true", help="Automatically choose another local port if needed.")
    parser.add_argument("--project-name", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        values = read_config()
        if args.action == "doctor":
            for check in check_prerequisites(local_frontend=False):
                print(check)
            if values.get("CONNECTOR_TOKEN"):
                print("Connector connection:", "ready" if session_ready(values) else "not running or still starting")
            return
        if args.action in {"setup", "start"}:
            setup_path = args.setup_file or (SETUP_FILE if args.action == "setup" and SETUP_FILE.exists() else None)
            if setup_path:
                values.update(import_setup(setup_path))
            if args.origin:
                values["CORS_ORIGINS"] = args.origin
            if args.port:
                values["CONNECTOR_PORT"] = str(args.port)
            if args.whisper_model:
                values["WHISPER_MODEL_SIZE"] = args.whisper_model
            if args.project_name:
                if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", args.project_name):
                    raise SetupError("Invalid local processing project name.")
                values["CONNECTOR_PROJECT_NAME"] = args.project_name
            if args.action == "setup" and not setup_path:
                values = guided_setup(values)
            if not values.get("CORS_ORIGINS"):
                raise SetupError("Run 'python local_connector.py' for guided setup, or supply --origin with your website address.")
            values["CORS_ORIGINS"] = trusted_origin(values["CORS_ORIGINS"])
            values.setdefault("CONNECTOR_PORT", "5000")
            values.setdefault("CONNECTOR_TOKEN", secrets.token_urlsafe(32))
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", values["CONNECTOR_TOKEN"]):
                raise SetupError("CONNECTOR_TOKEN must be a 32-128 character code using letters, digits, underscores or hyphens.")
            use_local_website = local_website(values) and not args.no_browser
            for check in check_prerequisites(local_frontend=use_local_website):
                print(check)
            if args.auto_port:
                values["CONNECTOR_PORT"] = str(choose_port(values))
            else:
                check_port(values)
            write_config(values)
            fingerprint = backend_fingerprint()
            image = values.get("CONNECTOR_IMAGE")
            if image:
                if not re.fullmatch(r"ghcr\.io/[a-z0-9_./-]+@sha256:[a-f0-9]{64}", image):
                    raise SetupError("The processing image must be a GHCR image pinned to its SHA256 digest.")
                command = compose() + ["up", "-d", "--no-build", "--pull", "missing"]
            else:
                needs_build = (args.rebuild or values.get("CONNECTOR_BUILD_FINGERPRINT") != fingerprint
                               or run_capture(["docker", "image", "inspect", "subtitled-connector:local"]).returncode != 0)
                command = compose() + ["up", "-d"] + (["--build"] if needs_build else [])
        else:
            if not CONFIG.exists():
                raise SetupError("Run 'python local_connector.py' first to set up this device.")
            if args.action == "code":
                print("Pairing code:", values["CONNECTOR_TOKEN"])
                return
            check_prerequisites()
            command = compose() + {
                "stop": ["down"], "logs": ["logs", "--tail", "100", "-f"],
                "prepare": ["run", "--rm", "--no-deps", "worker", "flask", "--app", "run", "prepare-transcription"],
                "prepare-translation": ["run", "--rm", "--no-deps", "worker", "flask", "--app", "run", "setup-local-translation", "--repair"],
            }[args.action]
        result = subprocess.run(command, cwd=ROOT, check=False, stdout=sys.stdout, stderr=sys.stderr,
                                **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
        if result.returncode:
            raise SetupError("The local services could not complete this step. Check the messages above; run the launcher again after correcting the issue.")
        if args.action in {"setup", "start"}:
            # Record a source version only after a successful build/start. Failed
            # upgrades must not cause a later launch to reuse an outdated image.
            values["CONNECTOR_BUILD_FINGERPRINT"] = fingerprint
            write_config(values)
            wait_for_connector(values)
            print("\nLocal connector:", connector_address(values))
            print("Trusted website:", values["CORS_ORIGINS"])
            if not args.quiet_pairing:
                print("Pairing code:", values["CONNECTOR_TOKEN"])
                print("\nEnter this code on the website. Transcription does not require KoboldCpp.")
            print("To download/check the transcription model in advance: python local_connector.py prepare")
            if not args.no_browser:
                if use_local_website:
                    start_local_website(values)
                else:
                    webbrowser.open(values["CORS_ORIGINS"])
    except (SetupError, argparse.ArgumentTypeError, OSError) as exc:
        print(f"\nSetup needs attention: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (KeyboardInterrupt, EOFError):
        print("\nSetup closed. Existing local files are preserved.")


if __name__ == "__main__":
    main()
