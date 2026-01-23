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

async def _execute_expired_offers_logic():
    
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
   
    async with AsyncSessionLocal() as db:

        print(f"Executando expiração da ofertas: {datetime.now()}")

        try:
            offers_query = text("""
                UPDATE offers
                 SET status = 'EXPIRED',
                    status_reason = 'AUTO_EXPIRED',
                    status_changed_by_staff_id = NULL
                WHERE end_at IS NOT NULL
                AND end_at <= now()
                AND status IN ('CREATED', 'ACTIVE', 'PAUSED');
            """)
        
            print("Ofertas alteradas para EXPIRED com sucesso.")

        except Exception as e:
            await db.rollback()
            print(f"Erro ao atualizar ofertas: {e}")
            
        await db.execute(offers_query)
        await db.commit()
        
    
        print("Ofertas alteradas para EXPIRED com sucesso.")   
        await engine.dispose()
    
    return f"Ciclo finalizado."

# ---------------------------------------------------------
# 3. A TAREFA DO CELERY (SYNC WRAPPER)
# ---------------------------------------------------------
@celery_app.task(name="app.tasks.expired_offers.update_expired_offers_task")
def update_expired_offers_task():
    """Wrapper síncrono para o Celery"""
    return asyncio.run(_execute_expired_offers_logic())