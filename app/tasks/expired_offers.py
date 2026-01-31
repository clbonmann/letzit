import os
import asyncio
import logging
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from celery import shared_task # <--- CORREÇÃO 2: Use shared_task

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

async def _execute_expired_offers_logic():
    # Cria engine local para garantir conexão limpa na task agendada
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    LocalSession = async_sessionmaker(engine, expire_on_commit=False) # Nome diferente para não confundir
   
    async with LocalSession() as db:
        logger.info(f"Iniciando ciclo de expiração: {datetime.now()}")

        try:
            # CORREÇÃO 1: Tudo dentro do Try
            offers_query = text("""
                UPDATE offers
                 SET status = 'EXPIRED',
                    status_reason = 'AUTO_EXPIRED',
                    status_changed_by_staff_id = NULL
                WHERE end_at IS NOT NULL
                AND end_at <= now()
                AND status IN ('CREATED', 'ACTIVE', 'PAUSED');
            """)
        
            # Executa DENTRO do bloco protegido
            result = await db.execute(offers_query)
            await db.commit()

            claims_query = text("""
                UPDATE offer_claims
                 SET status = 'NO_SHOW',
                updated_at = NOW(),
                penalty_applied_at = NOW()
                WHERE expires_at <= now()
                AND status IN ('ACCEPTED');
            """)
        
            # Executa DENTRO do bloco protegido
            result = await db.execute(claims_query)
            await db.commit()
            
            logger.info(f"Sucesso: {result.rowcount} ofertas expiradas.")

        except Exception as e:
            await db.rollback() # Agora o rollback funciona se o execute falhar
            logger.error(f"Erro crítico ao expirar ofertas: {e}")
            raise e # Relança o erro para o Celery saber que falhou
        finally:
            # Garante o fechamento da engine
            await engine.dispose()
    
    return "Ciclo finalizado."

# ---------------------------------------------------------
# 3. A TAREFA DO CELERY
# ---------------------------------------------------------
# CORREÇÃO 2: Usando shared_task para evitar erro de 'Unregistered task'
@shared_task(name="app.tasks.expired_offers.update_expired_offers_task")
def update_expired_offers_task():
    """Wrapper síncrono para o Celery"""
    return asyncio.run(_execute_expired_offers_logic())