import os
import asyncio
import logging
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from celery import shared_task # <--- CORREÇÃO CRÍTICA: Use shared_task

logger = logging.getLogger(__name__)

# -------------------------------------------
# 1. PREPARAÇÃO DA URL
# -------------------------------------------
raw_url = os.getenv("DATABASE_URL")
if not raw_url:
    raise ValueError("DATABASE_URL não configurada no ambiente")

if raw_url.startswith("postgres://"):
    DATABASE_URL = raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif raw_url.startswith("postgresql://") and "+asyncpg" not in raw_url:
    DATABASE_URL = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = raw_url

async def _update_restaurant_reputation_logic():
    # Cria engine dedicada para a task (evita stale connections)
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    LocalSession = async_sessionmaker(engine, expire_on_commit=False)
   
    async with LocalSession() as db:
        logger.info(f"Iniciando cálculo de reputação de restaurantes: {datetime.now()}")

        try:
            # Query otimizada:
            # 1. Usa restaurant_reputation (nome correto da coluna)
            # 2. Usa IS DISTINCT FROM para só atualizar se a nota mudou
            sql = text("""
                UPDATE restaurants r
                SET restaurant_reputation = sub.avg_total
                FROM (
                    SELECT 
                        restaurant_id, 
                        ROUND(AVG(average_score)::numeric, 1) as avg_total
                    FROM restaurant_reviews
                    GROUP BY restaurant_id
                ) AS sub
                WHERE r.id = sub.restaurant_id
                  AND (r.restaurant_reputation IS DISTINCT FROM sub.avg_total);
            """)
            
            # CORREÇÃO: Executa DENTRO do try
            result = await db.execute(sql)
            await db.commit()
            
            logger.info(f"Sucesso: Reputação atualizada para {result.rowcount} restaurantes.")

        except Exception as e:
            await db.rollback()
            logger.error(f"Erro ao atualizar reputação: {e}")
            raise e # Relança para o Celery saber que falhou
        finally:
            await engine.dispose()
    
    return "Ciclo finalizado."

# ---------------------------------------------------------
# 3. A TAREFA DO CELERY
# ---------------------------------------------------------
# CORREÇÃO: Nome deve bater com o beat_schedule e usar shared_task
@shared_task(name="app.tasks.restaurant_reputation.update_restaurant_reputation_task")
def update_restaurant_reputation_task():
    """Wrapper síncrono para o Celery"""
    return asyncio.run(_update_restaurant_reputation_logic())