import asyncio
import os
import logging
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.core.celery_app import celery_app
from app.models import OfferTarget, Offer, OfferClaim, Client

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

# -------------------------------------------
# 2. A LÓGICA (Async Puro com Engine Descartável)
# -------------------------------------------
async def _execute_matchmaking_logic():
    # Criamos engine local com NullPool usando a URL corrigida
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print(f"🎣 [Matchmaker] Iniciando ciclo de pescaria: {datetime.now()}")
        
        # 1. Buscar Ofertas Ativas
        offers_query = text("""
            SELECT 
                id, 
                geog, 
                radius_km, 
                max_target_total, 
                created_at, 
                end_at 
            FROM offers 
            WHERE status = 'ACTIVE' 
              AND end_at > NOW() 
              AND accept_limit - accepted_count > 0
        """)

        active_offers = (await db.execute(offers_query)).mappings().all()
        total_caught = 0

        for offer in active_offers:
            # --- LÓGICA DE BATCH ---
            count_query = text("SELECT count(*) FROM offer_targets WHERE offer_id = :oid")
            current_targets = (await db.execute(count_query, {"oid": offer.id})).scalar()

            limit_val = 500 # Default de segurança

            # Se tem limite total de alvos definido
            if offer.max_target_total > 0:
                remaining_slots = offer.max_target_total - current_targets
                if remaining_slots <= 0:
                    continue # Já atingiu o público alvo total
                limit_val = remaining_slots
            
            # --- LÓGICA DE INSERT (A PESCARIA) ---
            fishing_query = text(f"""
                INSERT INTO offer_targets (offer_id, client_id, batch_no, state, geog_cli, geog_res, target_distance, created_at, released_at)
                SELECT 
                    :oid,          -- offer_id
                    c.id,          -- client_id
                    1,             -- batch_no
                    'RELEASED',    -- state inicial
                    c.geog, 
                    :geog,
                    ST_Distance(c.geog, :geog),
                    :created_at,   -- created_at (Data da oferta)
                    NOW()          -- released_at (Data do disparo)
                FROM clients c
                WHERE 
                    c.is_deleted = FALSE 
                    AND (c.cooldown_until IS NULL OR c.cooldown_until < NOW())
                    AND c.last_loc_at > (NOW() - INTERVAL '15 minute')
                    
                    -- Filtro de Distância (Convertendo km para metros no parametro)
                    AND ST_DWithin(c.geog, :geog, :radius_meters)
                    
                    -- Anti-Spam
                    AND NOT EXISTS (
                        SELECT 1 FROM offer_targets t 
                        WHERE t.offer_id = :oid AND t.client_id = c.id
                    )
                
                ORDER BY ST_Distance(c.geog, :geog) ASC
                LIMIT :limit
                RETURNING client_id
            """)

            try:
                result = await db.execute(fishing_query, {
                    "oid": offer.id,
                    "created_at": offer.created_at,
                    "geog": offer.geog,
                    "radius_meters": offer.radius_km * 1000, # Conversão KM -> Metros
                    "limit": limit_val
                })
                
                count = result.rowcount
                if count > 0:
                    total_caught += count
                    print(f"   🐟 Oferta {offer.id}: Capturou {count} clientes.")
                    
            except Exception as e:
                print(f"   ❌ Erro na oferta {offer.id}: {e}")

        await db.commit()
    
    # --- LIMPEZA CRÍTICA ---
    await engine.dispose()
    
    return f"Ciclo finalizado. Total capturado: {total_caught}"

# ---------------------------------------------------------
# 3. A TAREFA DO CELERY (SYNC WRAPPER)
# ---------------------------------------------------------
@celery_app.task(name="app.tasks.matchmaker.run_matchmaker_cycle")
def run_matchmaker_cycle():
    """Wrapper síncrono para o Celery"""
    return asyncio.run(_execute_matchmaking_logic())