from celery import Celery
from app.settings import settings

broker = settings.CELERY_BROKER_URL or settings.REDIS_URL
backend = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL

celery_app = Celery("mvp", broker=broker, backend=backend)

@celery_app.task
def ping():
    return "pong"
