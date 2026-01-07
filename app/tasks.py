from celery import Celery
from app.settings import settings

celery_app = Celery(
    "letzit",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
)

