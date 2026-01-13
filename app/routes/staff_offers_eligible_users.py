from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])

@router.get("/{offer_id}/eligible-users")
async def eligible_users_for_offer(
    offer_id: int,
    active_minutes: int = Query(30, ge=1, le=240, description="Minutos desde a última localização"),
    limit: int = Query(5000, ge=1, le=10000, description="Limite de usuários para não travar o payload"),
    exclude_already_targeted: bool = Query(True, description="Ignorar usuários que já estão na lista de disparos dessa oferta"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    # ID do restaurante do usuário logado (Segurança)
    rid = int(staff["restaurant_id"])

    # 1) Busca dados da oferta e localização do restaurante em uma única query
    offer_data_query = await db.execute(
        text("""
            SELECT 
                o.id, 
                o.radius_km, 
                o.status, 
                r.geog AS restaurant_geog
            FROM offers o
            JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.id = :oid AND o.restaurant_id = :rid
        """),
        {"oid": offer_id, "rid": rid},
    )
    offer = offer_data_query.mappings().first()

    # Validações Iniciais
    if not offer:
        raise HTTPException(status_code=404, detail="Oferta não encontrada ou não pertence a este restaurante.")
    
    if offer["restaurant_geog"] is None:
        raise HTTPException(status_code=400, detail="Localização do restaurante não configurada.")

    if offer["radius_km"] is None:
        raise HTTPException(status_code=400, detail="Raio da oferta não definido.")

    # Converte raio para metros (PostGIS geography usa metros)
    radius_m = int(offer["radius_km"]) * 1000

    # 2) Construção da Query de usuários elegíveis
    # Otimização: Passamos o restaurant_geog recuperado acima como parâmetro :r_geog
    # Isso evita que o banco faça um JOIN ou Subquery para cada linha da tabela users.
    
    target_exclusion_sql = ""
    if exclude_already_targeted:
        target_exclusion_sql = """
            AND NOT EXISTS (
                SELECT 1 FROM offer_targets t 
                WHERE t.offer_id = :oid AND t.user_id = u.id
            )
        """

    users_query = text(f"""
        SELECT 
            u.id AS user_id,
            u.phone_e164,
            ST_Distance(u.geog, :r_geog)::int AS distance_m
        FROM users u
        WHERE u.geog IS NOT NULL
          AND u.is_blocked = FALSE
          AND (u.cooldown_until IS NULL OR u.cooldown_until < now())
          AND u.last_loc_at > (now() - make_interval(mins => :mins))
          AND ST_DWithin(u.geog, :r_geog, :radius_m)
          {target_exclusion_sql}
        ORDER BY distance_m ASC
        LIMIT :limit
    """)

    result = await db.execute(
        users_query,
        {
            "oid": offer_id,
            "r_geog": offer["restaurant_geog"],
            "mins": active_minutes,
            "radius_m": radius_m,
            "limit": limit
        }
    )
    
    eligible_users = result.mappings().all()

    return {
        "offer_id": offer_id,
        "restaurant_id": rid,
        "config": {
            "radius_km": offer["radius_km"],
            "active_minutes": active_minutes,
            "limit_applied": limit
        },
        "total_eligible": len(eligible_users),
        "users": eligible_users  # Lista de {user_id, phone_e164, distance_m}
    }
