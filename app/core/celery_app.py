import os
from celery import Celery
from celery.schedules import crontab

# O Railway injeta REDIS_URL automaticamente se os serviços estiverem linkados
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "letzit_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks.matchmaker"]
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"]
)

celery_app.conf.beat_schedule = {
    "run-matchmaker-every-minute": {
        "task": "app.tasks.matchmaker.run_matchmaker_cycle",
        "schedule": crontab(minute="*"),
    },

    'update-reputation-every-30-minutes': {
        'task': 'app.tasks.restaurant_reputation.update_restaurant_reputation_task',
        'schedule': crontab(minute='*/30'), # Roda a cada 30 minutos
    },
}