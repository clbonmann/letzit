from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.deps_user import get_current_user_id

router = APIRouter(prefix="/offers", tags=["offers"])

@router.get("/nearby")
async def offers_nearby(
    radius_km: int = 2,
    limit: int = 50,
    uid: int = Depends(get_current_user_id), 
    db: AsyncSession = Depends(get_db_session),
):
    # Validações rápidas em Python (custo zero)
    if not (1 <= radius_km <= 20):
        raise HTTPException(400, "radius_km must be between 1 and 20")
    
    if not (1 <= limit <= 200):
        raise HTTPException(400, "limit must be between 1 and 200")

    radius_m = radius_km * 1000

    # QUERY ÚNICA OTIMIZADA
    # 1. CTE 'user_ref': Pega a localização do usuário (garante que ele existe e tem local).
    # 2. JOINs diretos: Começamos de offer_targets (que são poucos registros por usuário)
    #    para evitar scannear a tabela inteira de restaurantes geometricamente.
    query = text("""
        WITH user_ref AS (
            SELECT geog 
            FROM users 
            WHERE id = :uid
        )
        SELECT
            o.id,
            o.restaurant_id,
            r.name AS restaurant_name,
            r.city AS restaurant_city,
            o.title,
            o.message,
            o.price_cents,
            o.radius_km,
            o.created_at,
            o.end_at,
            -- Calcula a distância em metros
            ST_Distance(u.geog, r.geog)::int AS distance_m
        FROM user_ref u
        CROSS JOIN offer_targets t
        JOIN offers o ON o.id = t.offer_id
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE 
            -- Filtros de Negócio (Target)
            t.user_id = :uid 
            AND t.released_at IS NOT NULL
            
            -- Filtros de Validade da Oferta
            AND o.placement = 'NORMAL'
            AND o.status = 'ACTIVE'
            AND o.end_at > NOW()
            
            -- Filtros Espaciais (PostGIS)
            AND r.geog IS NOT NULL
            AND ST_DWithin(u.geog, r.geog, :radius_m)
            
        ORDER BY distance_m ASC, o.created_at DESC
        LIMIT :limit
    """)

    result = await db.execute(query, {
        "uid": uid,
        "radius_m": radius_m,
        "limit": limit
    })
    
    rows = result.mappings().all()

    # Se a lista vier vazia, pode ser que o usuário não tenha local setado
    # ou realmente não tenha ofertas. 
    # Para distinguir, você teria que checar u_geog separadamente, 
    # mas para performance, assumimos que lista vazia é ok.
    
    return {
        "radius_km": radius_km,
        "count": len(rows),
        "items": rows,
    }
