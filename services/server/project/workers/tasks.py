from celery import Celery
import os

# Celery app is created standalone so it can be imported by workers without Flask context.
# The Flask app context is pushed manually inside tasks that need DB access.
celery_app = Celery(
    'mst',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://default:Ey@123!@redis:6379/0'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://default:Ey@123!@redis:6379/0'),
)

celery_app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
)


@celery_app.task(bind=True, name='workers.calibrate')
def calibrate_task(self, run_id: str):
    """
    Async calibration task. Implemented in Phase 3.
    Steps: load dataset → feature prep → model.fit → mlflow logging
           → artifact store → diagnostics → emit SocketIO progress.
    """
    raise NotImplementedError("Calibration task not yet implemented")
