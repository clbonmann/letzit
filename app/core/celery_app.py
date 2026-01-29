import os
from celery import Celery
from celery.schedules import crontab

# O Railway injeta REDIS_URL automaticamente se os serviços estiverem linkados
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "letzit_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.matchmaker", 
        "app.tasks.store_reputation",
        "app.tasks.expired_offers",
        "app.tasks.client_scoring" # <--- Adicionado: Nível/Reputação do Cliente
    ]
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
    # 1. MATCHMAKER: O coração do app (Roda todo minuto)
    "run-matchmaker-every-minute": {
        "task": "app.tasks.matchmaker.run_matchmaker_cycle",
        "schedule": crontab(minute="*"),
    },

    # 2. REPUTAÇÃO DO ESTABELECIMENTO (Roda a cada 30 min)
    'update-store-reputation-30-min': {
        'task': 'app.tasks.store_reputation.update_store_reputation_task',
        'schedule': crontab(minute='*/30'),
    },

    # 3. EXPIRAÇÃO DE OFERTAS (Roda a cada 30 min)
    'update-expired-offers-30-min': {
        'task': 'app.tasks.expired_offers.update_expired_offers_task',
        'schedule': crontab(minute='*/30'), 
    },

    # 4. NÍVEL E REPUTAÇÃO DO CLIENTE (Roda 1x por hora)
    # Importante para bloquear usuários com No-Show e subir o nível de quem usa
    'update-client-scores-hourly': {
        'task': 'app.tasks.client_scoring.update_client_scores_task',
        'schedule': crontab(minute='0'), # No minuto 0 de cada hora
    },
}