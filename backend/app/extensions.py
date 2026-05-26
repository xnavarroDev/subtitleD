from celery import Celery
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
celery_app = Celery("subtitled")


def init_celery(app):
    """Bind Celery to Flask configuration and application context.

    Celery tasks need Flask's config, logging, and SQLAlchemy session. Wrapping
    task execution in `app.app_context()` lets worker code use the same helpers
    as HTTP request handlers.
    """
    celery_app.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
        task_ignore_result=False,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        task_track_started=True,
    )

    class FlaskTask(celery_app.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app.Task = FlaskTask
    return celery_app
