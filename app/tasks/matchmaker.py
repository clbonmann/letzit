import asyncio
from datetime import datetime
from sqlalchemy import text
from app.db import async_session_factory # ou AsyncSessionLocal, conforme seu db.py
from app.core.celery_app import celery_app

# -------------------------------------------
# 1. A LÓGICA (Async Puro - Sem decorator Celery)
# -------------------------------------------
async def _execute_matchmaking_logic():
    async with async_session_factory() as db:
        print(f"🎣 [Matchmaker] Iniciando ciclo de pescaria: {datetime.now()}")
        
        # ... (Sua lógica de query e insert aqui, IGUAL estava antes) ...
        # Vou resumir aqui, mas mantenha o seu código completo do passo anterior
        
        offers_query = text("SELECT id, geog, radius_meters, batch_size FROM offers WHERE status = 'ACTIVE' AND expires_at > NOW() AND quantity_available > 0")
        active_offers = (await db.execute(offers_query)).mappings().all()

        total_caught = 0
        for offer in active_offers:
            # Lógica de Batch...
            
            # Lógica de Insert...
            # Mantenha seu código SQL aqui
            pass 

        await db.commit()
        return "Ciclo finalizado com sucesso."

# -------------------------------------------
# 2. A TAREFA (Síncrona - Com decorator Celery)
# -------------------------------------------
@celery_app.task
def run_matchmaker_cycle():
    """
    Esta é a função que o Celery chama.
    Ela cria um loop de eventos e roda a função async dentro dele.
    """
    # asyncio.run() é a forma moderna (Python 3.7+) de rodar async em contexto sync
    return asyncio.run(_execute_matchmaking_logic())