from celery import Celery
from app.settings import settings

celery_app = Celery(
    "letzit",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
)
