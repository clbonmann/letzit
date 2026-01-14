from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.deps_user import get_current_user_id

router = APIRouter(prefix="/offers", tags=["offers"])

@router.get("/picks")
async def get_picks(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    uid: int = Depends(get_current_user_id), 
    db: AsyncSession = Depends(get_db_session),
):
    """
    Retorna os convites (Picks) do usuário.
    Se o usuário for novo e não tiver convites, o sistema gera 5 agora mesmo.
    """

    # 1. Tenta buscar os convites já existentes (Cache/Histórico)
    query_existing = text("""
        SELECT 
            o.id,
            o.restaurant_id,
            r.name AS restaurant_name,
            r.logo_url,
            o.title,
            o.message,
            o.price_cents,
            o.original_price_cents,
            o.end_at,
            t.created_at as invited_at
        FROM offer_targets t
        JOIN offers o ON o.id = t.offer_id
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE 
            t.user_id = :uid 
            AND t.used_at IS NULL -- Ainda não usou
            AND o.status = 'ACTIVE'
            AND o.end_at > NOW()
        ORDER BY t.created_at DESC
        LIMIT 5
    """)

    result = await db.execute(query_existing, {"uid": uid})
    rows = result.mappings().all()

    # ---------------------------------------------------------
    # 2. LÓGICA DE "COLD START" (Usuário Novo / Sem Convites)
    # ---------------------------------------------------------
    if len(rows) == 0:
        # Se não tem convites, vamos criar agora! 
        # Precisamos da localização para isso.
        
        # Se o front não mandou lat/lon, pegamos do cadastro do user
        if lat is None or lon is None:
            user_geo = await db.execute(text("SELECT ST_Y(geog::geometry) as lat, ST_X(geog::geometry) as lon FROM users WHERE id=:uid"), {"uid": uid})
            geo_row = user_geo.first()
            if geo_row:
                lat, lon = geo_row.lat, geo_row.lon
            else:
                # Se não tem geo nenhuma, retorna vazio mesmo
                return {"title": "Sem convites", "items": []}

        # Query mágica: Busca ofertas próximas, CRIA o target e RETORNA os dados
        # Tudo numa tacada só para ser rápido.
        query_instant_match = text("""
            WITH new_matches AS (
                INSERT INTO offer_targets (user_id, offer_id, released_at)
                SELECT 
                    :uid, 
                    o.id, 
                    NOW()
                FROM offers o
                JOIN restaurants r ON r.id = o.restaurant_id
                WHERE 
                    o.status = 'ACTIVE' 
                    AND o.end_at > NOW()
                    AND o.placement = 'NORMAL'
                    AND ST_DWithin(
                        r.geog, 
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 
                        10000 -- Raio de 10km para garantir que ache algo
                    )
                ORDER BY 
                    ST_Distance(r.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) ASC
                LIMIT 5
                ON CONFLICT DO NOTHING -- Evita erro se já existir (raro)
                RETURNING offer_id, created_at
            )
            -- Agora seleciona os dados bonitos para exibir
            SELECT 
                o.id,
                o.restaurant_id,
                r.name AS restaurant_name,
                r.logo_url,
                o.title,
                o.message,
                o.price_cents,
                o.original_price_cents,
                o.end_at,
                nm.created_at as invited_at
            FROM new_matches nm
            JOIN offers o ON o.id = nm.offer_id
            JOIN restaurants r ON r.id = o.restaurant_id
        """)

        try:
            result = await db.execute(query_instant_match, {"uid": uid, "lat": lat, "lon": lon})
            await db.commit() # Importante commitar a criação dos targets
            rows = result.mappings().all()
        except Exception as e:
            await db.rollback()
            print(f"Erro no Instant Match: {e}")
            rows = []

    # 3. Retorno Final
    return {
        "title": "Escolhidos para Você", # Título emocional
        "count": len(rows),
        "items": rows
    }
    
@router.get("/home")
async def get_home_offers(
    # Lat/Lon ainda são vitais para ordenar por conveniência, 
    # mas não são o critério principal de "existência" da oferta.
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    uid: int = Depends(get_current_user_id), 
    db: AsyncSession = Depends(get_db_session),
):
    """
    O "Santo Graal" do App: As 5 ofertas exclusivas para o usuário.
    Não é uma busca. É a revelação dos "Matches" feitos pelo sistema.
    """

    # Lógica de Origem (igual anterior, fallback para o banco)
    if lat is not None and lon is not None:
        origin_sql = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"
        params = {"uid": uid, "lat": lat, "lon": lon}
    else:
        origin_sql = "(SELECT geog FROM users WHERE id = :uid)"
        params = {"uid": uid}

    query = text(f"""
        WITH user_loc AS (
            SELECT {origin_sql}::geography AS geog
        )
        SELECT 
            o.id,
            o.restaurant_id,
            r.name AS restaurant_name,
            r.logo_url,
            o.title,
            o.message,   -- A mensagem personalizada do dono ("Ei Osvaldo, vem cá!")
            o.price_cents,
            o.original_price_cents,
            o.end_at,
            ST_Distance(u.geog, r.geog)::int AS distance_m
            
        FROM user_loc u
        -- O CORAÇÃO DO SISTEMA: Só mostramos o que está na tabela de targets
        JOIN offer_targets t ON t.user_id = :uid 
        JOIN offers o ON o.id = t.offer_id
        JOIN restaurants r ON r.id = o.restaurant_id
        
        WHERE 
            t.released_at IS NOT NULL
            AND t.used_at IS NULL -- Ainda não usou
            AND o.status = 'ACTIVE'
            AND o.end_at > NOW()
            
            -- Trava de segurança geográfica ampla (ex: 30km)
            -- Só para garantir que não apareça algo impossível de ir.
            AND ST_DWithin(u.geog, r.geog, 30000) 

        -- A ORDENAÇÃO É A CHAVE DA EMOÇÃO:
        -- 1. Placement 'HIGHLIGHT' (Se tiver destaque pago/premium)
        -- 2. Recência (Acabou de ser convidado)
        -- 3. Distância (Desempate)
        ORDER BY 
            o.placement DESC,      -- Normal vs Highlight
            t.created_at DESC,     -- Os convites mais frescos primeiro
            distance_m ASC         -- Mais perto
            
        LIMIT 5 -- A Regra de Ouro
    """)

    result = await db.execute(query, params)
    rows = result.mappings().all()

    return {
        "title": "Seus Convites de Hoje",
        "subtitle": "Estes restaurantes escolheram você.",
        "count": len(rows),
        "items": rows,
    }
