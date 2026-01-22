import os
from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "letzit_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    # --- AQUI ESTÁ A CORREÇÃO ---
    # Adicione a lista 'include'. O Celery vai importar esses arquivos ao iniciar.
    # Verifique se o nome da pasta é 'tasks' ou 'scripts' (veja passo 2 abaixo)
    include=["app.tasks.matchmaker"] 
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Remove aquele aviso chato do log (deprecation warning)
    broker_connection_retry_on_startup=True, 
)

celery_app.conf.beat_schedule = {
    "run-matchmaker-every-minute": {
        # O caminho aqui DEVE bater com o 'include' e a pasta real
        "task": "app.tasks.matchmaker.run_fishing_job", 
        "schedule": crontab(minute="*"), 
    },
}