from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Dict

from fastapi import APIRouter, Depends, Header, Query, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.models import Restaurant
# IMPORTANDO SCHEMAS (Agora do lugar certo)
from app.schemas.staff import (
    DashboardStatsResponse,
    AudienceStatsResponse,
    AudienceBucket
)

router = APIRouter(prefix="/staff/stats", tags=["staff-stats"])

@router.get("/dashboard", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    days_revenue: int = Query(30, description="Dias para cálculo de receita total"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
    x_restaurant_id: int | None = Header(default=None, alias="x-restaurant-id"),
):
    logged_rid = int(staff["restaurant_id"])
    rid = logged_rid

    # Lógica Super Admin
    if staff.get("role") == "INTERNAL_ADMIN" and x_restaurant_id:
        rid = x_restaurant_id
    """
    Painel Principal:
    1. Resumo Financeiro (Últimos 30 dias).
    2. Operação de HOJE (Para o gerente acompanhar o movimento).
    3. Status das Ofertas (Quantas estão rodando).
    """
    now = datetime.now(timezone.utc)
    
    # Data de corte para Receita
    since_revenue = now - timedelta(days=days_revenue)
    
    # Data de corte para "Hoje" (início do dia UTC)
    start_of_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    # 1. Query Combinada: KPIs Financeiros e Diários
    kpi_query = text("""
        SELECT 
            -- Receita Total (Janela de dias)
            COALESCE(SUM(o.price_cents) FILTER (
                WHERE c.status = 'REDEEMED' AND c.redeemed_at >= :since_rev
            ), 0)::int as revenue,

            -- Operação HOJE: Aceites
            COUNT(c.id) FILTER (
                WHERE c.accepted_at >= :start_today
            )::int as today_accepted,

            -- Operação HOJE: Resgates (Vendas)
            COUNT(c.id) FILTER (
                WHERE c.status = 'REDEEMED' AND c.redeemed_at >= :start_today
            )::int as today_redeemed,

            -- Operação HOJE: No Shows
            COUNT(c.id) FILTER (
                WHERE c.status IN ('NO_SHOW', 'CANCELLED') 
                AND (c.expires_at >= :start_today OR c.canceled_at >= :start_today)
            )::int as today_no_show

        FROM offer_claims c
        JOIN offers o ON o.id = c.offer_id
        WHERE o.restaurant_id = :rid
    """)
    
    kpi = (await db.execute(kpi_query, {
        "rid": rid, 
        "since_rev": since_revenue, 
        "start_today": start_of_today
    })).mappings().first()

    # 2. Query de Ofertas Ativas (Agrupadas por tipo)
    active_query = text("""
        SELECT placement, COUNT(*)::int as qtd
        FROM offers 
        WHERE restaurant_id = :rid 
          AND status = 'ACTIVE' 
          AND end_at > NOW()
        GROUP BY placement
    """)
    
    active_rows = (await db.execute(active_query, {"rid": rid})).mappings().all()

    # Processamento dos Dados
    breakdown = {row.placement: row.qtd for row in active_rows}
    total_active = sum(breakdown.values())
    
    accepted = kpi.today_accepted or 0
    redeemed = kpi.today_redeemed or 0
    
    # Taxa de Conversão Diária
    conversion = (redeemed / accepted * 100) if accepted > 0 else 0.0

    stmt_lock = select(Restaurant).where(Restaurant.id == rid).with_for_update()
    result_lock = await db.execute(stmt_lock)
    restaurant = result_lock.scalar_one_or_none()
    if restaurant and restaurant.balance_km is not None:
        balance_km = restaurant.balance_km
    else:
        balance_km = 0.0

    return DashboardStatsResponse(
        total_revenue_cents=kpi.revenue or 0,
        
        today_accepted=accepted,
        today_redeemed=redeemed,
        today_no_shows=kpi.today_no_show or 0,
        balance_km=balance_km,
        conversion_rate_percent=conversion,
        active_offers_count=total_active,
        active_offers_breakdown=breakdown
    )


@router.get("/audience", response_model=AudienceStatsResponse)
async def get_audience_realtime(
    active_minutes: int = Query(60, ge=10, le=1440),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Mapa de Calor (Real-Time):
    Calcula quantos usuários ativos existem ao redor do restaurante AGORA.
    """
    rid = int(staff["restaurant_id"])

    # 1. Pega Geo do Restaurante
    rest = (await db.execute(
        text("SELECT geog FROM restaurants WHERE id = :rid"), 
        {"rid": rid}
    )).mappings().first()

    if not rest or not rest["geog"]:
        raise HTTPException(400, "Localização do restaurante não configurada.")

    # 2. Query Geoespacial (Buckets de Distância)
    query = text("""
        SELECT 
            COUNT(*) FILTER (WHERE ST_DWithin(u.geog, :r_geog, 1000))::int as km1,
            COUNT(*) FILTER (WHERE ST_DWithin(u.geog, :r_geog, 3000))::int as km3,
            COUNT(*) FILTER (WHERE ST_DWithin(u.geog, :r_geog, 5000))::int as km5,
            COUNT(*) FILTER (WHERE ST_DWithin(u.geog, :r_geog, 10000))::int as km10
        FROM clients u
        WHERE u.geog IS NOT NULL
          AND u.is_blocked = FALSE
          AND u.last_loc_at > (NOW() - make_interval(mins => :mins))
    """)

    counts = (await db.execute(query, {
        "r_geog": rest["geog"], 
        "mins": active_minutes
    })).mappings().first()

    # 3. Formata Resposta
    buckets = [
        AudienceBucket(radius_km=1, client_count=counts.km1, label="Vizinhos (1km)"),
        AudienceBucket(radius_km=3, client_count=counts.km3, label="Bairro (3km)"),
        AudienceBucket(radius_km=5, client_count=counts.km5, label="Região (5km)"),
        AudienceBucket(radius_km=10, client_count=counts.km10, label="Cidade (10km)")
    ]

    return AudienceStatsResponse(
        total_nearby=counts.km10,
        active_window_minutes=active_minutes,
        breakdown=buckets,
        computed_at=datetime.now(timezone.utc)
    )

