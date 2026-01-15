from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/stats", tags=["staff-stats"])

# --- SCHEMAS ---

class DashboardStats(BaseModel):
    # Financeiro
    total_revenue_cents: int
    
    # Operacional Hoje
    today_accepted: int
    today_redeemed: int
    today_no_shows: int
    conversion_rate: float
    
    # Gestão de Ofertas
    active_offers_count: int
    active_offers_breakdown: Dict[str, int] # Ex: {"NORMAL": 5, "CITY_HOME": 1}

class AudienceBucket(BaseModel):
    radius_km: int
    user_count: int
    label: str

class AudienceStats(BaseModel):
    total_nearby: int
    active_window_minutes: int
    breakdown: List[AudienceBucket]
    computed_at: datetime

# --- ENDPOINTS ---

@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    days_revenue: int = Query(30, description="Dias para cálculo de receita total"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Painel Principal:
    1. Resumo Financeiro (Últimos 30 dias).
    2. Operação de HOJE (Para o gerente acompanhar o movimento).
    3. Status das Ofertas (Quantas estão rodando).
    """
    rid = int(staff["restaurant_id"])
    now = datetime.now(timezone.utc)
    
    # Data de corte para Receita (ex: últimos 30 dias)
    since_revenue = now - timedelta(days=days_revenue)
    
    # Data de corte para "Hoje" (início do dia UTC)
    # Nota: Em produção, idealmente ajustar para o timezone do restaurante
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

            -- Operação HOJE: No Shows (Gente que aceitou mas não foi ou cancelou hoje)
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

    return DashboardStats(
        total_revenue_cents=kpi.revenue or 0,
        
        today_accepted=accepted,
        today_redeemed=redeemed,
        today_no_shows=kpi.today_no_show or 0,
        conversion_rate=round(conversion, 1),
        
        active_offers_count=total_active,
        active_offers_breakdown=breakdown
    )


@router.get("/audience", response_model=AudienceStats)
async def get_audience_realtime(
    active_minutes: int = Query(60, ge=10, le=1440),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Mapa de Calor (Real-Time):
    Calcula quantos usuários ativos existem ao redor do restaurante AGORA.
    Não usa cache para garantir dados frescos durante o MVP.
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
    # Conta usuários únicos ativos recentemente em cada raio
    query = text("""
        SELECT 
            COUNT(*) FILTER (WHERE ST_DWithin(u.geog, :r_geog, 1000))::int as km1,
            COUNT(*) FILTER (WHERE ST_DWithin(u.geog, :r_geog, 3000))::int as km3,
            COUNT(*) FILTER (WHERE ST_DWithin(u.geog, :r_geog, 5000))::int as km5,
            COUNT(*) FILTER (WHERE ST_DWithin(u.geog, :r_geog, 10000))::int as km10
        FROM users u
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
        AudienceBucket(radius_km=1, user_count=counts.km1, label="Vizinhos (1km)"),
        AudienceBucket(radius_km=3, user_count=counts.km3, label="Bairro (3km)"),
        AudienceBucket(radius_km=5, user_count=counts.km5, label="Região (5km)"),
        AudienceBucket(radius_km=10, user_count=counts.km10, label="Cidade (10km)")
    ]

    return AudienceStats(
        total_nearby=counts.km10,
        active_window_minutes=active_minutes,
        breakdown=buckets,
        computed_at=datetime.now(timezone.utc)
    )
