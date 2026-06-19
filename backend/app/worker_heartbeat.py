import json
import os
import socket
import threading
import time

from celery.signals import worker_ready, worker_shutdown
from redis import Redis


_stop_event = threading.Event()
_heartbeat_thread = None
_heartbeat_key = None


def register_worker_heartbeat(celery_app, flask_app):
    """Publish a Redis heartbeat independently of the worker's task pool."""

    @worker_ready.connect(weak=False)
    def start_heartbeat(**_kwargs):
        global _heartbeat_key, _heartbeat_thread

        _stop_event.clear()
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        key_prefix = flask_app.config["WORKER_HEARTBEAT_KEY_PREFIX"]
        _heartbeat_key = f"{key_prefix}{worker_id}"
        _heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(
                flask_app.config["CELERY_BROKER_URL"],
                _heartbeat_key,
                worker_id,
                flask_app.config["WORKER_HEARTBEAT_INTERVAL_SECONDS"],
                flask_app.config["WORKER_HEARTBEAT_TTL_SECONDS"],
                flask_app.logger,
            ),
            name="worker-heartbeat",
            daemon=True,
        )
        _heartbeat_thread.start()

    @worker_shutdown.connect(weak=False)
    def stop_heartbeat(**_kwargs):
        _stop_event.set()
        if _heartbeat_thread:
            _heartbeat_thread.join(timeout=2)
        if _heartbeat_key:
            try:
                client = Redis.from_url(flask_app.config["CELERY_BROKER_URL"])
                client.delete(_heartbeat_key)
                client.close()
            except Exception:
                flask_app.logger.warning(
                    "Could not remove the Celery worker heartbeat key.",
                    exc_info=True,
                )


def _heartbeat_loop(redis_url, key, worker_id, interval_seconds, ttl_seconds, logger):
    client = Redis.from_url(
        redis_url,
        socket_connect_timeout=min(float(interval_seconds), 2),
        socket_timeout=min(float(interval_seconds), 2),
    )
    try:
        while not _stop_event.is_set():
            payload = json.dumps(
                {
                    "worker": worker_id,
                    "updated_at": time.time(),
                }
            )
            try:
                client.set(key, payload, ex=max(1, int(ttl_seconds)))
            except Exception:
                logger.warning("Could not publish the Celery worker heartbeat.", exc_info=True)
            _stop_event.wait(float(interval_seconds))
    finally:
        client.close()
