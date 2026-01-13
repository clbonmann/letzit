from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.deps_staff import get_current_staff # Assumindo que é para o dono do restaurante
from app.schemas.staff_stats import (
    DashboardStatsResponse
)
router = APIRouter(prefix="/staff/stats", tags=["staff-dashboard"])

@router.get("/today", response_model=DashboardStatsResponse)
async def get_today_stats(
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    restaurant_id = int(staff["restaurant_id"])

    # Query Poderosa: Faz 3 coisas ao mesmo tempo
    # 1. Conta ofertas ativas agrupadas por tipo (placement)
    # 2. Conta estatísticas de claims (aceites) de HOJE
    
    # Parte A: Ofertas Ativas
    offers_query = text("""
        SELECT placement, COUNT(*) as qtd
        FROM offers
        WHERE restaurant_id = :rid
          AND status = 'ACTIVE'
          AND end_at > NOW()
        GROUP BY placement
    """)

    # Parte B: KPIs de Claims de Hoje
    # Consideramos "Hoje" baseado no servidor (UTC). 
    # Para produção ideal, deverias converter para o fuso do restaurante.
    kpi_query = text("""
        SELECT 
            -- Total aceites hoje (claims criados hoje)
            COUNT(*) FILTER (WHERE c.created_at >= CURRENT_DATE) as accepted_today,
            
            -- Total validados hoje (claims queimados hoje)
            COUNT(*) FILTER (WHERE c.redeemed_at >= CURRENT_DATE) as redeemed_today,
            
            -- No-Shows de hoje (Criados hoje + Expirados hoje + Status do CLAIM é ACCEPTED)
            COUNT(*) FILTER (
                WHERE c.created_at >= CURRENT_DATE 
                AND c.expires_at < NOW() 
                AND c.status = 'ACCEPTED' -- <--- AQUI ESTAVA O ERRO (Agora é c.status)
            ) as no_shows_today
            
        FROM offer_claims c
        JOIN offers o ON o.id = c.offer_id
        WHERE o.restaurant_id = :rid
    """)

    # Executa as queries em paralelo (ou sequencial rápido)
    active_res = await db.execute(offers_query, {"rid": restaurant_id})
    kpi_res = (await db.execute(kpi_query, {"rid": restaurant_id})).mappings().first()

    # Processa Ofertas Ativas
    breakdown = {}
    total_active = 0
    for row in active_res:
        placement = row[0] # Ex: 'NORMAL'
        count = row[1]     # Ex: 3
        breakdown[placement] = count
        total_active += count

    # Processa KPIs
    accepted = kpi_res["accepted_today"] or 0
    redeemed = kpi_res["redeemed_today"] or 0
    no_shows = kpi_res["no_shows_today"] or 0

    # Evita divisão por zero
    conversion = 0.0
    if accepted > 0:
        conversion = round((redeemed / accepted) * 100, 1)

    return {
        "active_offers_count": total_active,
        "active_offers_breakdown": breakdown,
        "today_accepted": accepted,
        "today_redeemed": redeemed,
        "today_conversion_rate": conversion,
        "today_expired_no_show": no_shows
    }
