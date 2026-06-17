from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.health.ping")
def ping() -> str:
    return "pong"
