"""Pair a hosted interface with a loopback-only local processing service."""

import hashlib
import hmac
import secrets
import time
import threading
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, request
from werkzeug.exceptions import HTTPException


connector_bp = Blueprint("connector", __name__, url_prefix="/api/connector")
PROTOCOL_VERSION = 1
MEDIA_ENDPOINTS = {"api.source_media", "api.rendered_media", "api.download_srt", "api.download_render"}


@connector_bp.errorhandler(HTTPException)
def connector_error(exc):
    return jsonify({"error": exc.description}), exc.code


def _signature(value):
    return hmac.new(
        current_app.config["CONNECTOR_TOKEN"].encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def _media_token():
    value = f"{int(time.time()) + 43200}.{secrets.token_hex(16)}"
    return f"{value}.{_signature(value)}"


def _valid_media_token(token):
    try:
        expiry, nonce, signature = token.split(".")
        return int(expiry) > time.time() and hmac.compare_digest(
            signature.encode(), _signature(f"{expiry}.{nonce}").encode()
        )
    except (ValueError, AttributeError):
        return False


def init_connector(app):
    enabled = app.config.get("CONNECTOR_MODE", False)
    if enabled and len(app.config.get("CONNECTOR_TOKEN", "")) < 32:
        raise ValueError("Connector mode requires a CONNECTOR_TOKEN of at least 32 characters.")
    if enabled and (not app.config["CORS_ORIGINS"] or "*" in app.config["CORS_ORIGINS"]):
        raise ValueError("Connector mode requires explicit trusted CORS_ORIGINS.")
    app.extensions["connector_pairing"] = {"tickets": {}, "lock": threading.Lock()}

    @app.before_request
    def protect_connector():
        if not enabled:
            return None
        # Validate Host as well as Origin to reject DNS rebinding. Docker publishes
        # the service on loopback; its internal bind address remains 0.0.0.0.
        if urlsplit(f"http://{request.host}").hostname not in {"localhost", "127.0.0.1", "::1"}:
            abort(403, description="Local connector must be accessed through localhost.")
        origin = request.headers.get("Origin")
        if origin and origin not in app.config["CORS_ORIGINS"]:
            abort(403, description="This website is not paired with the local connector.")
        if request.method == "OPTIONS" or request.path == "/health":
            return None
        if request.endpoint == "connector.redeem_pairing" and request.method == "POST":
            # This endpoint authenticates a single-use, origin-bound handoff.
            return None
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if hmac.compare_digest(supplied.encode(), app.config["CONNECTOR_TOKEN"].encode()):
            return None
        # Video tags and ordinary downloads cannot attach an Authorization header.
        # Give them an expiring, read-only credential instead of the pairing secret.
        if request.method in {"GET", "HEAD"} and request.endpoint in MEDIA_ENDPOINTS:
            if _valid_media_token(request.args.get("media_token", "")):
                return None
        abort(401, description="Enter the pairing code shown by your local connector.")

    @app.after_request
    def private_response(response):
        if enabled:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.register_blueprint(connector_bp)


@connector_bp.post("/pairing-ticket")
def issue_pairing():
    if not current_app.config.get("CONNECTOR_MODE"):
        abort(409, description="Companion pairing requires protected connector mode.")
    data = request.get_json(silent=True)
    origin = data.get("origin") if isinstance(data, dict) else None
    if origin not in current_app.config["CORS_ORIGINS"]:
        abort(403, description="Approve this website in the companion first.")
    pairing = current_app.extensions["connector_pairing"]
    ticket = secrets.token_urlsafe(32)
    with pairing["lock"]:
        now = time.time()
        pairing["tickets"] = {key: value for key, value in pairing["tickets"].items() if value[1] > now}
        if len(pairing["tickets"]) >= 32:
            abort(429, description="Too many pending connections. Try again in two minutes.")
        pairing["tickets"][hashlib.sha256(ticket.encode()).hexdigest()] = (origin, now + 120)
    return jsonify({"ticket": ticket, "expires_in": 120})


@connector_bp.post("/pair")
def redeem_pairing():
    if not current_app.config.get("CONNECTOR_MODE"):
        abort(409, description="Companion pairing requires protected connector mode.")
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    ticket = data.get("ticket")
    if not isinstance(ticket, str) or len(ticket) > 128:
        abort(401, description="Open the website from the companion to connect again.")
    pairing = current_app.extensions["connector_pairing"]
    with pairing["lock"]:
        key = hashlib.sha256(ticket.encode()).hexdigest()
        entry = pairing["tickets"].get(key)
        if not entry or entry[1] <= time.time() or entry[0] != request.headers.get("Origin"):
            abort(401, description="This connection link expired. Open the website from the companion again.")
        del pairing["tickets"][key]
    return jsonify({"code": current_app.config["CONNECTOR_TOKEN"]})


@connector_bp.post("/session")
def connect_session():
    enabled = current_app.config.get("CONNECTOR_MODE", False)
    return jsonify({
        "name": "SubtitleD local connector",
        "protocol_version": PROTOCOL_VERSION,
        "protected": enabled,
        "media_token": _media_token() if enabled else None,
        "media_token_expires_in": 43200 if enabled else None,
        "capabilities": ["transcribe", "translate", "render"],
    })
