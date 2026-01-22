import asyncio
from datetime import datetime
from sqlalchemy import text
from app.db import AsyncSessionLocal as async_session_factory
from app.core.celery_app import celery_app

# -------------------------------------------
# 1. A LÓGICA (Async Puro - Sem decorator Celery)
# -------------------------------------------
async def _execute_matchmaking_logic():
    async with async_session_factory() as db:
        print(f"🎣 [Matchmaker] Iniciando ciclo de pescaria: {datetime.now()}")
        
        # ... (Sua lógica de query e insert aqui, IGUAL estava antes) ...
        # Vou resumir aqui, mas mantenha o seu código completo do passo anterior
        
        offers_query = text("SELECT id, geog, radius_km, max_target_total, created_at, end_at FROM offers WHERE status = 'ACTIVE' AND end_at > NOW() AND accept_limit - accepted_count > 0")

        active_offers = (await db.execute(offers_query)).mappings().all()
        total_caught = 0

        for offer in active_offers:
            # --- LÓGICA DE BATCH ---
            # Verifica quantos targets já foram disparados para essa oferta
            count_query = text("SELECT count(*) FROM offer_targets WHERE offer_id = :oid")
            current_targets = (await db.execute(count_query, {"oid": offer.id})).scalar()

            limit_clause = ""
            limit_val = 500 # Default de segurança

            # Se tem batch definido pelo restaurante
            if offer.max_target_total > 0:
                remaining_slots = offer.max_target_total - current_targets
                if remaining_slots <= 0:
                    continue # Batch já está cheio, pula para a próxima oferta
                limit_val = remaining_slots
            
            # --- LÓGICA DE INSERT (A PESCARIA) ---
            # Seleciona clientes elegíveis e insere na tabela targets
            fishing_query = text(f"""
                INSERT INTO offer_targets (offer_id, client_id, batch_no, state, created_at, released_at)
                SELECT 
                    :oid,          -- offer_id
                    c.id,          -- client_id
                    1,             -- batch_no
                    'RELEASED',    -- state inicial
                    :created_at,    -- created_at
                    NOW()          -- released_at
                FROM clients c
                WHERE 
                    c.is_active = TRUE 
                    AND (c.quarantine_until IS NULL OR c.quarantine_until < NOW())
                    AND c.last_location_at > (NOW() - INTERVAL '15 minute') -- Peixe vivo (visto há 15min)
                    
                    -- Filtro de Distância (PostGIS)
                    AND ST_DWithin(c.geog, :geog, :radius)
                    
                    -- Anti-Spam: Não enviar se já recebeu
                    AND NOT EXISTS (
                        SELECT 1 FROM offer_targets t 
                        WHERE t.offer_id = :oid AND t.client_id = c.id
                    )
                
                -- Ordenar: Quem está mais perto recebe primeiro
                ORDER BY ST_Distance(c.geog, :geog) ASC
                
                LIMIT :limit
                RETURNING client_id
            """)

            try:
                result = await db.execute(fishing_query, {
                    "oid": offer.id,
                    "created_at": offer.created_at,
                    "geog": offer.geog,
                    "radius": offer.radius_km*1000, # Converter km para metros
                    "limit": limit_val
                })
                
                count = result.rowcount
                if count > 0:
                    total_caught += count
                    print(f"   🐟 Oferta {offer.id}: Capturou {count} clientes.")
                    
            except Exception as e:
                print(f"   ❌ Erro na oferta {offer.id}: {e}")

        await db.commit()
        return f"Ciclo finalizado. Total capturado: {total_caught}"

# ---------------------------------------------------------
# 2. A TAREFA DO CELERY (SYNC WRAPPER)
# Esta é a função que o Celery chama. Ela apenas roda o Async acima.
# ---------------------------------------------------------
@celery_app.task
def run_matchmaker_cycle():
    # Cria um novo loop de eventos para rodar o código assíncrono
    return asyncio.run(_execute_matchmaking_logic())