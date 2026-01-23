from sqlalchemy import text
from app.db import AsyncSessionLocal # Use sua conexão de banco aqui
import asyncio
import os
import logging
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.models import Offer
from app.core import celery_app

logger = logging.getLogger(__name__)
# -------------------------------------------
# 1. PREPARAÇÃO DA URL (CORREÇÃO DO ERRO)
# -------------------------------------------
raw_url = os.getenv("DATABASE_URL")

if not raw_url:
    raise ValueError("DATABASE_URL não configurada no ambiente")

# O Railway fornece 'postgres://', mas o SQLAlchemy Async precisa de 'postgresql+asyncpg://'
if raw_url.startswith("postgres://"):
    DATABASE_URL = raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif raw_url.startswith("postgresql://") and "+asyncpg" not in raw_url:
    # Caso venha postgresql:// mas sem o driver async
    DATABASE_URL = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = raw_url

async def _update_restaurant_reputation_logic():
    
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
   
    async with AsyncSessionLocal() as db:

        print(f"Executando média reviews restaurantes: {datetime.now()}")

    #Recalcula a média de avaliações de todos os restaurantes
    #e atualiza a coluna 'reputation' na tabela 'restaurants'.
        try:
            # Query atômica para recalcular e atualizar
            sql = text("""
                UPDATE restaurants r
                SET reputation = sub.avg_total
                FROM (
                    SELECT 
                        restaurant_id, 
                        ROUND(AVG(average_score)::numeric, 1) as avg_total
                    FROM restaurant_reviews
                    GROUP BY restaurant_id
                ) AS sub
                WHERE r.id = sub.restaurant_id;
            """)
            print("Reputação dos restaurantes atualizada com sucesso.")
        except Exception as e:
            await db.rollback()
            print(f"Erro ao atualizar reputação: {e}")

        await db.execute(sql)
        await db.commit()        
        print("Reviews atualizadas com sucesso.")   
        await engine.dispose()
    
    return f"Ciclo finalizado."

# ---------------------------------------------------------
# 3. A TAREFA DO CELERY (SYNC WRAPPER)
# ---------------------------------------------------------
@celery_app.task(name="app.tasks.restaurant_reputation.update_restaurant_reputation_task")
def update_restaurant_reputation_task():
    """Wrapper síncrono para o Celery"""
    return asyncio.run(_update_restaurant_reputation_logic())