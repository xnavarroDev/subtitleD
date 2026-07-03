import time

from flask import Flask, jsonify
from flask_cors import CORS
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from .config import Config
from .diagnostics import register_diagnostics_cli
from .local_translation_cli import register_local_translation_cli
from .extensions import db, init_celery
from .utils.files import ensure_storage_dirs


def create_app(config_object=Config):
    """Create and configure the Flask application.

    The app factory keeps API serving, tests, and Celery worker startup on the
    same initialization path. In local MVP mode it also creates tables
    automatically so `docker compose up --build` is enough to start working.
    """
    app = Flask(__name__)
    app.config.from_object(config_object)

    ensure_storage_dirs(app.config["STORAGE_DIR"])

    db.init_app(app)
    init_celery(app)

    CORS(app, origins=app.config["CORS_ORIGINS"], supports_credentials=False)

    from .routes import api_bp

    app.register_blueprint(api_bp)
    register_diagnostics_cli(app)
    register_local_translation_cli(app)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    if app.config.get("CREATE_TABLES", True):
        with app.app_context():
            _create_tables_with_retry(app)

    return app


def _create_tables_with_retry(app, attempts=30, delay_seconds=1):
    """Create development tables, retrying while Postgres finishes booting."""
    from . import models  # noqa: F401

    for attempt in range(1, attempts + 1):
        try:
            db.create_all()
            _upgrade_dev_schema()
            return
        except OperationalError:
            db.session.remove()
            if attempt == attempts:
                raise
            app.logger.info("Database not ready, retrying table creation.")
            time.sleep(delay_seconds)


def _upgrade_dev_schema():
    """Apply tiny additive schema changes for the migration-free MVP database."""
    inspector = inspect(db.engine)
    table_columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
    }
    additions = {
        "projects": {
            "min_speakers": "INTEGER",
            "max_speakers": "INTEGER",
            "processing_stage": "VARCHAR(64)",
            "processing_warning": "VARCHAR(1000)",
            "translation_completed_words": "INTEGER DEFAULT 0",
            "translation_total_words": "INTEGER DEFAULT 0",
            "glossary": "TEXT",
            "translation_temperature": "FLOAT DEFAULT 0.7",
            "translation_top_p": "FLOAT DEFAULT 0.6",
            "translation_top_k": "INTEGER DEFAULT 20",
            "translation_repetition_penalty": "FLOAT DEFAULT 1.05",
            "translation_max_tokens": "INTEGER DEFAULT 256",
            "translation_context_captions": "INTEGER DEFAULT 2",
            "detected_source_language": "VARCHAR(32)",
            "detect_speakers": "BOOLEAN DEFAULT FALSE",
            "smooth_speaker_fragments": "BOOLEAN DEFAULT FALSE",
        },
        "subtitle_segments": {
            "speaker_label": "VARCHAR(64)",
            "transcription_confidence": "FLOAT",
            "translation_method": "VARCHAR(32) DEFAULT 'deterministic_timing'",
            "timing_quality": "VARCHAR(32) DEFAULT 'forced_aligned'",
            "translation_provider": "VARCHAR(64) DEFAULT 'unknown'",
            "translation_model": "VARCHAR(255)",
            "source_reconstruction_method": "VARCHAR(128) DEFAULT 'raw'",
            "source_was_reconstructed": "BOOLEAN DEFAULT FALSE",
            "translation_unit_id": "VARCHAR(64)",
            "translation_confidence_warning": "VARCHAR(255)",
        },
        "transcript_words": {
            "timing_quality": "VARCHAR(32) DEFAULT 'forced_aligned'",
        },
    }

    with db.engine.begin() as connection:
        for table, columns in additions.items():
            existing_columns = table_columns.get(table, set())
            for column_name, column_type in columns.items():
                if column_name not in existing_columns:
                    connection.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")
                    )
