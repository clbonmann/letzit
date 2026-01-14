from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.deps_user import get_current_user_id

router = APIRouter(prefix="/offers", tags=["offers"])

@router.get("/nearby")
async def offers_nearby(
    # Parâmetros opcionais de GPS Real-time (O App manda se tiver)
    lat: Optional[float] = Query(None, description="Latitude atual do usuário"),
    lon: Optional[float] = Query(None, description="Longitude atual do usuário"),
    
    radius_km: int = 2,
    limit: int = 50,
    uid: int = Depends(get_current_user_id), 
    db: AsyncSession = Depends(get_db_session),
):
    # 1. Validações
    if not (1 <= radius_km <= 50): # Aumentei um pouco para áreas rurais/subúrbio
        raise HTTPException(400, "radius_km must be between 1 and 50")

    radius_m = radius_km * 1000

    # 2. Definição do Ponto de Origem (Dinâmico vs Banco)
    # Se o front mandou lat/lon, criamos um ponto na hora.
    # Se não mandou, pegamos do banco (users.geog).
    
    # Fragmento SQL para decidir a origem:
    if lat is not None and lon is not None:
        # Usa o GPS do celular agora
        origin_sql = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"
        params = {"uid": uid, "radius_m": radius_m, "limit": limit, "lat": lat, "lon": lon}
    else:
        # Usa o último local conhecido no banco
        origin_sql = "(SELECT geog FROM users WHERE id = :uid)"
        params = {"uid": uid, "radius_m": radius_m, "limit": limit}

    # 3. A Query
    query = text(f"""
        WITH user_loc AS (
            SELECT {origin_sql}::geography AS geog
        )
        SELECT 
            o.id,
            o.restaurant_id,
            r.name AS restaurant_name,
            r.city AS restaurant_city,
            r.logo_url,           -- Adicionei: Essencial para o Feed
            o.title,
            o.message,
            o.price_cents,
            o.original_price_cents, -- Adicionei: Para mostrar o desconto (De: X Por: Y)
            o.end_at,
            
            -- Distância calculada em relação à origem definida acima
            ST_Distance(u.geog, r.geog)::int AS distance_m
            
        FROM user_loc u
        CROSS JOIN offer_targets t
        JOIN offers o ON o.id = t.offer_id
        JOIN restaurants r ON r.id = o.restaurant_id
        
        WHERE 
            -- 1. Vínculo com usuário
            t.user_id = :uid 
            AND t.released_at IS NOT NULL
            AND t.used_at IS NULL  -- CRÍTICO: Não mostrar se já usou!
            
            -- 2. Validade da Oferta
            AND o.placement = 'NORMAL'
            AND o.status = 'ACTIVE'
            AND o.end_at > NOW()
            -- CRÍTICO: Não mostrar se já esgotou a quantidade global
            AND (o.max_qty IS NULL OR o.claimed_count < o.max_qty)

            -- 3. Filtro Geográfico (Raio do Usuário)
            AND r.geog IS NOT NULL
            AND ST_DWithin(u.geog, r.geog, :radius_m)
            
            -- 4. Filtro Geográfico (Raio do Restaurante)
            -- Se o restaurante disse "só quero gente a 1km", respeitamos,
            -- mesmo que o usuário tenha pedido raio de 20km.
            AND ST_DWithin(u.geog, r.geog, o.radius_km * 1000)

        ORDER BY distance_m ASC, o.created_at DESC
        LIMIT :limit
    """)

    result = await db.execute(query, params)
    rows = result.mappings().all()

    return {
        "user_coords": {"lat": lat, "lon": lon} if lat else "database_fallback",
        "radius_applied_km": radius_km,
        "count": len(rows),
        "items": rows,
    }
