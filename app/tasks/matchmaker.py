import asyncio
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db import AsyncSessionLocal as async_session_factory
from app.core.celery_app import celery_app # Assumindo que o app está aqui

@celery_app.task
async def run_matchmaker_cycle():
    """
    Roda o ciclo de pescaria:
    1. Busca ofertas ativas.
    2. Para cada oferta, busca clientes elegíveis respeitando o batch.
    3. Insere os targets.
    """
    async with async_session_factory() as db:
        print(f"🎣 [Matchmaker] Iniciando ciclo de pescaria: {datetime.now()}")
        
        # 1. Buscar Ofertas que precisam de peixes
        offers_query = text("""
            SELECT 
                id, 
                restaurant_id, 
                batch_size, 
                geog, -- O objeto Geography do PostGIS
                radius_meters
            FROM offers 
            WHERE status = 'ACTIVE' 
              AND expires_at > NOW() 
              AND quantity_available > 0
        """)
        
        # mappings() retorna um objeto tipo dict-like
        active_offers = (await db.execute(offers_query)).mappings().all()

        for offer in active_offers:
            await process_single_offer(db, offer)

        await db.commit()

async def process_single_offer(db: AsyncSession, offer):
    # 2. Verificar quantos targets já foram disparados (controle de Batch)
    count_query = text("SELECT count(*) FROM offer_targets WHERE offer_id = :oid")
    current_targets = (await db.execute(count_query, {"oid": offer.id})).scalar()

    limit_clause = ""
    
    # Se tem batch definido
    if offer.batch_size > 0:
        remaining_slots = offer.batch_size - current_targets
        if remaining_slots <= 0:
            return # Batch já está cheio
        limit_clause = f"LIMIT {remaining_slots}"
    else:
        # Batch 0 = ilimitado (mas limitamos por ciclo para segurança)
        limit_clause = "LIMIT 500" 

    # 3. O INSERT Mágico
    # Correção: Usamos :geog diretamente ao invés de reconstruir o ponto com lat/lon
    fishing_query = text(f"""
        INSERT INTO offer_targets (offer_id, client_id, batch_no, state, created_at, released_at)
        SELECT 
            :oid,          -- offer_id
            c.id,          -- client_id
            1,             -- batch_no
            'RELEASED',    -- state inicial
            NOW(),         -- created_at
            NOW()          -- released_at
        FROM clients c
        WHERE 
            c.is_active = TRUE 
            AND (c.quarantine_until IS NULL OR c.quarantine_until < NOW())
            AND c.last_location_at > (NOW() - INTERVAL '15 minute')
            
            -- CORREÇÃO AQUI: Sintaxe limpa de Geography vs Geography
            AND ST_DWithin(c.geog, :geog, :radius)
            
            AND NOT EXISTS (
                SELECT 1 FROM offer_targets t 
                WHERE t.offer_id = :oid AND t.client_id = c.id
            )
        
        -- Ordenar por proximidade usando o geog da oferta
        ORDER BY ST_Distance(c.geog, :geog) ASC
        
        {limit_clause}
    """)

    try:
        result = await db.execute(fishing_query, {
            "oid": offer.id,    # FALTAVA ISSO
            "geog": offer.geog, # Passa o objeto geography direto
            "radius": offer.radius_meters or 20000 # Default 20km se for null
        })
        
        if result.rowcount > 0:
            print(f"   🐟 Oferta {offer.id}: Pescou {result.rowcount} novos clientes.")
            
    except Exception as e:
        print(f"   ❌ Erro ao processar oferta {offer.id}: {e}")