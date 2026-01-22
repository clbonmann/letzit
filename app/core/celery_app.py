import os
from celery import Celery

# Pega a URL do Redis das variáveis de ambiente ou usa local
REDIS_URL = os.getenv("REDIS_URL", "redis.railway.internal:6379/0")

celery_app = Celery(
    "letzit_worker",
    broker=REDIS_URL,
    backend=REDIS_URL
)

# Configurações do Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Configura o agendamento (Beat)
celery_app.conf.beat_schedule = {
    "run-matchmaker-every-minute": {
        "task": "app.scripts.matchmaker.run_fishing_job",
        "schedule": 60.0, # Executa a cada 60 segundos
    },
}