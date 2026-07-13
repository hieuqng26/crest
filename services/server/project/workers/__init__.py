import os

from celery import Celery

celery_app = Celery(
    "mst",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    include=["project.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_default_queue="default",
    # File exports run on a dedicated queue (consumed by the `export-worker`
    # service) so a heavy csv/xlsx build never delays the calibration/forecast/
    # credit pipeline on `default`.
    task_routes={
        "export_dataset": {"queue": "exports"},
        "purge_expired_exports": {"queue": "exports"},
    },
    # Beat sweep: reclaim expired export files + rows hourly.
    beat_schedule={
        "purge-expired-exports": {
            "task": "purge_expired_exports",
            "schedule": 3600.0,
        },
    },
)
