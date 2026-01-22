import asyncio
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db import async_session_factory # Seu factory de sessão

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
        # (Ativas, no prazo, com tickets sobrando)
        offers_query = text("""
            SELECT 
                id, 
                restaurant_id, 
                batch_size, 
                geog,-- assumindo que salvamos a lat/lon do restaurante na oferta ou fazemos join
                radius_meters
            FROM offers 
            WHERE status = 'ACTIVE' 
              AND expires_at > NOW() 
              AND quantity_available > 0
        """)
        
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
            return # Batch já está cheio, não pesca mais ninguém
        limit_clause = f"LIMIT {remaining_slots}"
    else:
        # Se batch é 0 (ilimitado), limitamos por segurança (ex: 100 por minuto) 
        # para não travar o banco num insert gigante
        limit_clause = "LIMIT 500" 

    # 3. O INSERT Mágico
    # Seleciona clientes que atendem aos critérios e já insere na tabela targets
    fishing_query = text(f"""
        INSERT INTO offer_targets (offer_id, client_id, batch_no, state, created_at, released_at)
        SELECT 
            :oid,          -- offer_id
            c.id,          -- client_id
            1,             -- batch_no (podemos melhorar isso depois)
            'RELEASED',    -- state inicial
            NOW(),         -- created_at
            NOW()          -- released_at
        FROM clients c
        WHERE 
            -- Critério 1: Cliente Ativo e Saudável
            c.is_active = TRUE 
            AND (c.quarantine_until IS NULL OR c.quarantine_until < NOW())
            
            -- Critério 2: Localização Recente (15 min)
            AND c.last_location_at > (NOW() - INTERVAL '15 minute')
            
            -- Critério 3: Proximidade (Geografia)
            AND ST_DWithin(c.geog, :geog, 4326)::geography, :radius)     
            -- Critério 4: Ainda não recebeu esta oferta (Anti-Spam)
            AND NOT EXISTS (
                SELECT 1 FROM offer_targets t 
                WHERE t.offer_id = :oid AND t.client_id = c.id
            )
        
        -- Ordenar por proximidade (pega os mais pertos primeiro)
        ORDER BY ST_Distance(c.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) ASC
        
        {limit_clause}
    """)

    try:
        result = await db.execute(fishing_query, {
            "geog": offer.geog,
            "radius": offer.radius_meters # Default 20km
        })
        if result.rowcount > 0:
            print(f"   🐟 Oferta {offer.id}: Pescou {result.rowcount} novos clientes.")
    except Exception as e:
        print(f"   ❌ Erro ao processar oferta {offer.id}: {e}")