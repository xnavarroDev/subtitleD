import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import click
from flask import current_app
from redis import Redis
from sqlalchemy import text

from .extensions import celery_app, db


PASS = "pass"
WARN = "warn"
FAIL = "fail"

_DEEP_CACHE = {}
_DEEP_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    status: str
    message: str
    details: dict = field(default_factory=dict)

    @property
    def ready(self):
        return self.status != FAIL

    def to_dict(self, include_details=True):
        data = {
            "name": self.name,
            "status": self.status,
            "message": self.message,
        }
        if include_details and self.details:
            data["details"] = self.details
        return data


@dataclass(frozen=True)
class DiagnosticReport:
    mode: str
    checks: tuple[DiagnosticCheck, ...]
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    cached: bool = False

    @property
    def ready(self):
        return all(check.ready for check in self.checks)

    @property
    def status(self):
        return "ready" if self.ready else "unavailable"

    def to_dict(self, include_details=True):
        return {
            "status": self.status,
            "ready": self.ready,
            "mode": self.mode,
            "cached": self.cached,
            "checked_at": self.checked_at,
            "checks": [
                check.to_dict(include_details=include_details) for check in self.checks
            ],
        }


class PreflightError(RuntimeError):
    def __init__(self, report):
        self.report = report
        failures = [check.message for check in report.checks if check.status == FAIL]
        super().__init__(failures[0] if failures else "Job preflight failed.")


def run_system_diagnostics(deep=False, refresh=False, load_models=False):
    """Run global runtime diagnostics, caching expensive deep checks briefly."""
    cached = False
    if deep and not load_models and not refresh:
        transcription_check = _get_cached_deep_check()
        cached = transcription_check is not None
    else:
        transcription_check = None

    if transcription_check is None:
        transcription_check = check_transcription_provider(
            deep=deep,
            load_models=load_models,
        )
        if deep and not load_models:
            _cache_deep_check(transcription_check)

    checks = (
        check_database(),
        check_redis(),
        check_worker(),
        check_storage(),
        check_ffmpeg(require_subtitles=True),
        transcription_check,
        check_translation_provider(),
    )
    mode = "model_load" if load_models else ("deep" if deep else "quick")
    return DiagnosticReport(mode=mode, checks=checks, cached=cached)


def run_job_preflight(job_type, project, include_worker=True):
    """Run the checks required to safely queue or execute one job."""
    checks = [
        check_database(),
        check_redis(),
        check_storage(),
    ]
    if include_worker:
        checks.append(check_worker())

    source_path = getattr(project, "source_video_path", None)
    checks.append(check_project_file(source_path, "source_video"))

    if job_type == "process":
        checks.extend([
            check_ffmpeg(require_subtitles=False),
            check_transcription_provider(
                deep=False, diarize=bool(getattr(project, "detect_speakers", False))
            ),
        ])
        from .providers.translation import normalize_language

        source = normalize_language(getattr(project, "source_language", None))
        target = normalize_language(getattr(project, "target_language", None))
        if source == "auto" or source != target:
            checks.append(check_translation_provider(
                source_language=getattr(project, "source_language", None),
                target_language=getattr(project, "target_language", None),
            ))
    elif job_type == "render":
        checks.extend(
            [
                check_ffmpeg(require_subtitles=True),
                check_project_segments(project),
            ]
        )
    else:
        checks.append(
            DiagnosticCheck(
                name="job",
                status=FAIL,
                message=f"Unknown job type: {job_type}",
            )
        )

    return DiagnosticReport(mode=f"{job_type}_preflight", checks=tuple(checks))


def require_job_preflight(job_type, project, include_worker=True):
    report = run_job_preflight(job_type, project, include_worker=include_worker)
    if not report.ready:
        raise PreflightError(report)
    return report


def check_database():
    try:
        db.session.execute(text("SELECT 1"))
        return DiagnosticCheck("database", PASS, "Database connection is ready.")
    except Exception:
        db.session.rollback()
        return DiagnosticCheck(
            "database",
            FAIL,
            "Database connection failed.",
        )


def check_redis():
    timeout = float(current_app.config.get("DIAGNOSTICS_TIMEOUT_SECONDS", 2))
    urls = {
        current_app.config["CELERY_BROKER_URL"],
        current_app.config["CELERY_RESULT_BACKEND"],
    }
    clients = []
    try:
        for url in urls:
            client = Redis.from_url(
                url,
                socket_connect_timeout=timeout,
                socket_timeout=timeout,
            )
            clients.append(client)
            client.ping()
        return DiagnosticCheck("redis", PASS, "Redis broker and result backend are ready.")
    except Exception:
        return DiagnosticCheck(
            "redis",
            FAIL,
            "Redis broker or result backend is unavailable.",
        )
    finally:
        for client in clients:
            client.close()


def check_worker():
    timeout = float(current_app.config.get("WORKER_PING_TIMEOUT_SECONDS", 2))
    key_prefix = current_app.config.get(
        "WORKER_HEARTBEAT_KEY_PREFIX",
        "subtitled:workers:heartbeat:",
    )
    client = None
    try:
        client = Redis.from_url(
            current_app.config["CELERY_BROKER_URL"],
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )
        heartbeat_keys = list(client.scan_iter(match=f"{key_prefix}*", count=100))
    except Exception:
        heartbeat_keys = []
    finally:
        if client:
            client.close()

    if heartbeat_keys:
        return DiagnosticCheck(
            "worker",
            PASS,
            "Celery worker is ready.",
            {
                "source": "heartbeat",
                "worker_count": len(heartbeat_keys),
            },
        )

    # The control ping covers the short startup window before the first
    # heartbeat is published and workers that predate heartbeat support.
    try:
        replies = celery_app.control.ping(timeout=timeout)
    except Exception:
        replies = []
    if not replies:
        return DiagnosticCheck(
            "worker",
            FAIL,
            "No Celery worker responded to the readiness ping.",
        )
    nodes = sorted(
        node
        for reply in replies
        for node, response in reply.items()
        if response and response.get("ok") == "pong"
    )
    if not nodes:
        return DiagnosticCheck(
            "worker",
            FAIL,
            "Celery workers responded without a valid pong.",
        )
    return DiagnosticCheck(
        "worker",
        PASS,
        "Celery worker is ready.",
        {"source": "control_ping", "workers": nodes},
    )


def check_storage():
    storage_dir = Path(current_app.config["STORAGE_DIR"])
    required_dirs = [
        storage_dir / name
        for name in ("uploads", "audio", "exports", "renders", "models")
    ]
    missing = [str(path) for path in required_dirs if not path.is_dir()]
    if missing:
        return DiagnosticCheck(
            "storage",
            FAIL,
            "Required storage directories are missing.",
            {"missing": missing},
        )

    try:
        for directory in required_dirs:
            with tempfile.NamedTemporaryFile(dir=directory):
                pass
    except OSError:
        return DiagnosticCheck(
            "storage",
            FAIL,
            "One or more storage directories are not writable.",
        )

    free_bytes = shutil.disk_usage(storage_dir).free
    minimum_free = int(current_app.config.get("MIN_FREE_STORAGE_BYTES", 1024**3))
    if free_bytes < minimum_free:
        return DiagnosticCheck(
            "storage",
            WARN,
            "Storage is writable but available disk space is low.",
            {"free_bytes": free_bytes, "minimum_free_bytes": minimum_free},
        )
    return DiagnosticCheck(
        "storage",
        PASS,
        "Storage directories are writable.",
        {"free_bytes": free_bytes},
    )


def check_ffmpeg(require_subtitles=False):
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return DiagnosticCheck("ffmpeg", FAIL, "FFmpeg is not installed or not on PATH.")

    timeout = float(current_app.config.get("DIAGNOSTICS_TIMEOUT_SECONDS", 2))
    try:
        version = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        if version.returncode != 0:
            raise RuntimeError
        first_line = (version.stdout or "").splitlines()[0]

        if require_subtitles:
            filters = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-filters"],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            if filters.returncode != 0 or " subtitles " not in f" {filters.stdout} ":
                return DiagnosticCheck(
                    "ffmpeg",
                    FAIL,
                    "FFmpeg is installed but the subtitles filter is unavailable.",
                )
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        return DiagnosticCheck("ffmpeg", FAIL, "FFmpeg readiness check failed.")

    return DiagnosticCheck(
        "ffmpeg",
        PASS,
        "FFmpeg is ready.",
        {"version": first_line},
    )


def check_transcription_provider(deep=False, load_models=False, diarize=None):
    try:
        from .providers import get_transcription_provider

        provider = get_transcription_provider()
        return provider.check_ready(
            deep=deep, load_models=load_models, diarize=diarize
        )
    except Exception as exc:
        return DiagnosticCheck(
            "transcription",
            FAIL,
            _safe_error_message(exc, "Transcription provider readiness check failed."),
        )


def check_translation_provider(source_language=None, target_language=None):
    try:
        from .providers import get_translation_provider

        provider = get_translation_provider()
        return provider.check_ready(
            source_language=source_language,
            target_language=target_language,
        )
    except Exception as exc:
        return DiagnosticCheck(
            "translation",
            FAIL,
            _safe_error_message(exc, "Translation provider readiness check failed."),
        )


def check_project_file(path, name):
    if not path:
        return DiagnosticCheck(name, FAIL, "Project has no uploaded source video.")
    source = Path(path)
    if not source.is_file():
        return DiagnosticCheck(name, FAIL, "Project source video file is missing.")
    if not os.access(source, os.R_OK):
        return DiagnosticCheck(name, FAIL, "Project source video file is not readable.")
    return DiagnosticCheck(name, PASS, "Project source video is readable.")


def check_project_segments(project):
    if not getattr(project, "segments", None):
        return DiagnosticCheck(
            "subtitle_segments",
            FAIL,
            "Project has no subtitle segments to render.",
        )
    return DiagnosticCheck(
        "subtitle_segments",
        PASS,
        "Project subtitle segments are ready.",
    )


def register_diagnostics_cli(app):
    @app.cli.command("diagnostics")
    @click.option("--deep", is_flag=True, help="Run provider model and access checks.")
    @click.option(
        "--load-models",
        is_flag=True,
        help="Load WhisperX models in this isolated CLI process.",
    )
    @click.option("--refresh", is_flag=True, help="Ignore a cached deep diagnostics result.")
    @click.option("--json-output", is_flag=True, help="Print machine-readable JSON.")
    def diagnostics_command(deep, load_models, refresh, json_output):
        """Check whether runtime dependencies and providers are ready."""
        report = run_system_diagnostics(
            deep=deep or load_models,
            refresh=refresh,
            load_models=load_models,
        )
        if json_output:
            click.echo(json.dumps(report.to_dict(), indent=2))
        else:
            click.echo(f"Diagnostics: {report.status} ({report.mode})")
            for check in report.checks:
                click.echo(f"[{check.status.upper()}] {check.name}: {check.message}")
        if not report.ready:
            raise click.exceptions.Exit(1)


def clear_diagnostics_cache():
    with _DEEP_CACHE_LOCK:
        _DEEP_CACHE.clear()


def _get_cached_deep_check():
    ttl = float(current_app.config.get("DIAGNOSTICS_DEEP_CACHE_TTL_SECONDS", 300))
    with _DEEP_CACHE_LOCK:
        cached = _DEEP_CACHE.get("transcription")
    if not cached:
        return None
    cached_at, check = cached
    if time.monotonic() - cached_at > ttl:
        return None
    return check


def _cache_deep_check(check):
    with _DEEP_CACHE_LOCK:
        _DEEP_CACHE["transcription"] = (time.monotonic(), check)


def _safe_error_message(exc, fallback):
    message = str(exc).strip()
    if not message:
        return fallback
    return message[:1000]
