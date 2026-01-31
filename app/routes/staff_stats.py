from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select, text, desc, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.models import Store, StoreAccount, Offer, OfferTarget, OfferClaim
from app.schemas.staff import (
    DashboardStatsResponse,
    DashboardFinanceStats,
    DashboardFunnelStats,
    EngagementStats,
    TimeCycleStats,
    ActiveOfferDetail
)

router = APIRouter(prefix="/staff/stats", tags=["staff-stats"])

@router.get("/dashboard", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    # MUDANÇA: Aceitamos uma string 'range' em vez de 'days_window'
    range_option: str = Query("30d", alias="range", description="7d, 30d, 60d, 90d, ytd, mtd, wtd, all"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
    x_store_id: int | None = Header(default=None, alias="x-store-id"),
):
    logged_rid = int(staff["store_id"])
    rid = logged_rid

    if staff.get("role") == "INTERNAL_ADMIN" and x_store_id:
        rid = x_store_id
        
    now = datetime.now(timezone.utc)
    start_of_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    
    # LÓGICA DE DATA DINÂMICA
    historical_start = now - timedelta(days=30) # Default

    opt = range_option.lower()
    
    if opt == "7d":
        historical_start = now - timedelta(days=7)
    elif opt == "30d":
        historical_start = now - timedelta(days=30)
    elif opt == "60d":
        historical_start = now - timedelta(days=60)
    elif opt == "90d":
        historical_start = now - timedelta(days=90)
    elif opt == "wtd":
        # Começo da semana (Segunda-feira = 0)
        historical_start = start_of_today - timedelta(days=start_of_today.weekday())
    elif opt == "mtd":
        # Começo do mês atual
        historical_start = start_of_today.replace(day=1)
    elif opt == "ytd":
        # Começo do ano atual
        historical_start = start_of_today.replace(month=1, day=1)
    elif opt == "all":
        # Data muito antiga (Início da operação)
        historical_start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    # ==========================================================================
    # 1. FINANCEIRO (Ledger)
    # ==========================================================================
    finance_query = text("""
      SELECT 
        sum(credit) FILTER (WHERE date_of_bte >= :hist_start)::int as total_credit, 
        sum(debit) FILTER (WHERE date_of_bte >= :hist_start)::int as total_debit, 
        sum(balance_ta) FILTER (WHERE is_current = TRUE)::int as balance_ta,
        sum(debit*cost_ta_cents) FILTER (WHERE date_of_bte >= :hist_start)::float/100 as total_cost,
        sum(cost_package_cents) FILTER (WHERE date_of_bte >= :hist_start)::float/100 as total_purchase,
        sum(balance_ta*cost_ta_cents) FILTER (WHERE date_of_bte >= :hist_start and is_current = TRUE)::float/100 as total_balance,
        max(cost_ta_cents) filter (where is_current = TRUE)::float/100 as cost_ta_cents_current
        FROM store_account 
        where store_id = :rid ;
    """)

    last_entry = (await db.execute(finance_query, {
        "rid": rid, 
        "hist_start": historical_start
    })).mappings().first()
   
    finance_stats = DashboardFinanceStats(
        balance_ta=last_entry.balance_ta or 0,
        avg_cost_per_ta=last_entry.cost_ta_cents_current or 0.0,
        stock_value_reais=last_entry.total_balance or 0.0,
        total_credit=last_entry.total_credit or 0,
        total_debit=last_entry.total_debit or 0,
        total_cost=last_entry.total_cost or 0.0,
        total_purchase=last_entry.total_purchase or 0.0,
        total_balance=last_entry.total_balance or 0.0,
    )

    # ==========================================================================
    # 2. FUNIL DE VENDAS (Hoje + Receita Janela)
    # ==========================================================================
    kpi_query = text("""
        SELECT 
          COUNT(DISTINCT ot.client_id) FILTER (
                WHERE ot.state = 'REDEEMED' AND ot.redeemed_at >= :hist_start
            )::int as unique_clients,  
            COUNT(ot.client_id ) FILTER (WHERE ot.released_at >= :today)::int as today_reached,             
            COUNT(ot.client_id) FILTER (WHERE ot.viewed_at >= :today)::int as today_viewed,
            COUNT(ot.client_id) FILTER (WHERE ot.clicked_at >= :today)::int as today_clicked,
            COUNT(ot.client_id) FILTER (WHERE ot.accepted_at >= :today)::int as today_accepted,
            COUNT(ot.client_id) FILTER (WHERE ot.cancelled_at >= :today)::int as today_cancelled,
            COUNT(ot.client_id) FILTER (WHERE ot.redeemed_at >= :today)::int as today_redeemed,
            COUNT(ot.client_id) FILTER (WHERE ot.released_at >= :hist_start)::int as total_reached,             
            COUNT(ot.client_id) FILTER (WHERE ot.viewed_at >= :hist_start)::int as total_viewed,
            COUNT(ot.client_id) FILTER (WHERE ot.clicked_at >= :hist_start)::int as total_clicked,
            COUNT(ot.client_id) FILTER (WHERE ot.accepted_at >= :hist_start)::int as total_accepted,
            COUNT(ot.client_id) FILTER (WHERE ot.cancelled_at >= :hist_start)::int as total_cancelled,
            COUNT(ot.client_id) FILTER (WHERE ot.redeemed_at >= :hist_start)::int as total_redeemed,
            count(ot.client_id) FILTER (WHERE ot.state = 'NO_SHOW' AND ot.expired_at >= :hist_start) as total_no_show,
            COALESCE(AVG(ot.target_distance), 0) as avg_dist,
            
            -- Tempos (em Segundos -> converteremos para minutos no Python)
            -- Release -> View
            AVG(EXTRACT(EPOCH FROM (ot.viewed_at - ot.released_at))) FILTER (WHERE ot.viewed_at > ot.released_at) as sec_to_view,
            
            -- Release -> Accept
            AVG(EXTRACT(EPOCH FROM (ot.accepted_at - ot.released_at))) FILTER (WHERE ot.accepted_at > ot.released_at) as sec_to_accept,
            
            -- Release -> Redeem
            AVG(EXTRACT(EPOCH FROM (ot.redeemed_at - ot.released_at))) FILTER (WHERE ot.redeemed_at > ot.released_at) as sec_to_redeem
        FROM offer_targets ot
        WHERE ot.store_id = :rid
    """)
    
    kpi = (await db.execute(kpi_query, {
        "rid": rid, 
        "hist_start": historical_start, 
        "today": start_of_today
    })).mappings().first()
    
    funnel_stats = DashboardFunnelStats(
        today_reached=kpi.today_reached or 0,
        today_viewed=kpi.today_viewed or 0,
        today_clicked=kpi.today_clicked or 0,
        today_accepted=kpi.today_accepted or 0,
        today_redeemed=kpi.today_redeemed or 0,
        today_cancelled=kpi.today_cancelled or 0,
        today_conversion_rate=(kpi.today_clicked or 0) / (kpi.today_viewed or 1) * 100 if (kpi.today_viewed or 0) > 0 else 0.0,
        today_cancellation_rate=(kpi.today_cancelled or 0) / (kpi.today_accepted or 1) * 100 if (kpi.today_accepted or 0) > 0 else 0.0
    )

    # Sub-queries para "Melhor Tipo" e "Melhor Placement" (Top 1)
    # Baseado em volume de aceites
    best_type_query = text("""
        SELECT o.offer_type 
        FROM offer_targets t JOIN offers o ON o.id = t.offer_id
        WHERE o.store_id = :rid AND t.accepted_at >= :hist_start
        GROUP BY o.offer_type ORDER BY COUNT(t.client_id) DESC LIMIT 1
    """)
    best_placement_query = text("""
        SELECT o.placement
        FROM offer_targets t JOIN offers o ON o.id = t.offer_id
        WHERE o.store_id = :rid AND t.accepted_at >= :hist_start
        GROUP BY o.placement ORDER BY COUNT(t.client_id) DESC LIMIT 1
    """)
    
    best_type = (await db.execute(best_type_query, {"rid": rid, "hist_start": historical_start})).scalar()
    best_placement = (await db.execute(best_placement_query, {"rid": rid, "hist_start": historical_start})).scalar()

    engagement_stats = EngagementStats(
        total_reached_count=kpi.total_reached or 0,
        total_viewed_count=kpi.total_viewed or 0,
        total_clicked_count=kpi.total_clicked or 0,
        total_cancelled_count=kpi.total_cancelled or 0,
        total_no_shows_count=kpi.total_no_show or 0,
        total_accepted_count=kpi.total_accepted or 0,
        total_conversion_rate=round((kpi.total_accepted or 0) / (kpi.total_viewed or 1) * 100 if (kpi.total_viewed or 0) > 0 else 0.0, 2),
        total_cancellation_rate=round((kpi.total_cancelled or 0) / (kpi.total_accepted or 1) * 100 if (kpi.total_accepted or 0) > 0 else 0.0, 2),
        avg_distance_km=round(float(kpi.avg_dist or 0) / 1000.0, 1), 
        best_placement=best_placement,
        best_offer_type=best_type,
        cost_over_aquistion= round(float((last_entry.total_cost or 0) / kpi.total_redeemed if kpi.total_redeemed > 0 else 0.0), 2) if kpi.total_redeemed else 0.0
    )

    cycle_stats = TimeCycleStats(
        # Aplicamos float() aqui também por segurança
        avg_time_to_view_min=round(float(kpi.sec_to_view or 0) / 60.0, 1),
        avg_time_to_accept_min=round(float(kpi.sec_to_accept or 0) / 60.0, 1),
        avg_time_to_redeem_min=round(float(kpi.sec_to_redeem or 0) / 60.0, 1)
    )

    # ==========================================================================
    # 4. LISTA DE OFERTAS ATIVAS (Snapshot em Tempo Real)
    # ==========================================================================
    # Queremos saber o status atual de cada oferta ativa
    active_query = text("""
        SELECT 
            o.id, 
            o.title, 
            o.placement, 
            o.start_at, -- ou o.created_at se preferir
            o.audience_estimate,
            
            -- Métricas Reais
            (SELECT COUNT(*) FROM offer_targets WHERE offer_id = o.id) as reached,
            o.accepted_count,
            (SELECT COUNT(*) FROM offer_claims WHERE offer_id = o.id AND status='REDEEMED') as redeemed

        FROM offers o
        WHERE o.store_id = :rid 
          AND o.status = 'ACTIVE' 
          AND o.end_at > NOW()
        ORDER BY o.start_at DESC
    """)
    
    active_rows = (await db.execute(active_query, {"rid": rid})).mappings().all()
    
    active_offers_clean = []
    for row in active_rows:
        # Calculo de minutos ativa
        mins_active = 0
        if row.start_at:
            delta = now - row.start_at
            mins_active = int(delta.total_seconds() / 60)
            
        conv = (row.accepted_count / row.reached * 100) if row.reached > 0 else 0.0
        
        active_offers_clean.append(ActiveOfferDetail(
            offer_id=row.id,
            title=row.title,
            placement=row.placement,
            minutes_active=mins_active,
            audience_expected=row.audience_estimate or 0,
            reached_count=row.reached or 0,
            accepted_count=row.accepted_count or 0,
            redeemed_count=row.redeemed or 0,
            conversion_percent=round(conv, 1) or 0.0
        ))

    # ==========================================================================
    # 5. RETORNO FINAL
    # ==========================================================================
    return DashboardStatsResponse(
        finance=finance_stats,
        funnel=funnel_stats,
        engagement=engagement_stats,
        cycle_times=cycle_stats,
        active_offers_list=active_offers_clean
    )