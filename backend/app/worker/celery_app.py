from celery import Celery

from app.config import settings

celery_app = Celery("xoxoedu", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=2,
)

celery_app.autodiscover_tasks(["app.modules.auth", "app.modules.certificates", "app.modules.admin"])
