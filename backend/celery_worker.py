from app import create_app
from app.extensions import celery_app
from app.worker_heartbeat import register_worker_heartbeat

flask_app = create_app()

# Import task modules after the Flask app configures Celery so decorators register
# against the worker instance used by the celery CLI.
import app.tasks  # noqa: E402,F401

register_worker_heartbeat(celery_app, flask_app)
