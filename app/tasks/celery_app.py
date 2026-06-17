from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "knowledge_assistant",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.health", "app.tasks.documents"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
