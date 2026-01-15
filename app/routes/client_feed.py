from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session, AsyncSessionLocal
from app.deps_user import get_current_user_id

router = APIRouter(prefix="/client/offers", tags=["client-feed"])

# --- SCHEMAS ---

class AcceptOfferResponse(BaseModel):
    status: str
    offer_id: int
    user_id: int | None = None
    expires_at: datetime | None = None
    qr_token: str | None = None
    accepted_count: int | None = None
    accept_limit: int | None = None

# --- BACKGROUND TASKS ---

async def log_analytics_task(offer_id: int, user_id: int, event: str):
    """Registra eventos de analytics em background."""
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                text("INSERT INTO offer_analytics (offer_id, user_id, event_type) VALUES (:oid, :uid, :evt)"),
                {"oid": offer_id, "uid": user_id, "evt": event}
            )
            await session.commit()
        except Exception as e:
            print(f"[Analytics Error] {e}")

# --- READ ENDPOINTS (Feed & Map) ---

@router.get("/picks")
async def get_picks(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    city_slug: Optional[str] = Query(None, description="Opcional. Se não vier, tentamos detectar via GPS."),
    uid: int = Depends(get_current_user_id), 
    db: AsyncSession = Depends(get_db_session),
):
    """
    FEED HÍBRIDO INTELIGENTE:
    1. Tenta identificar a cidade (via parametro OU via GPS do usuário).
    2. Se a cidade tiver ofertas 'CITY_HOME' (Destaques), mostra elas.
    3. Se não tiver destaques (Interior/Cidade pequena), cai no modo 'PROXIMITY' e mostra o que tiver perto.
    """
    
    # --- 1. AUTO-DETECÇÃO DE CIDADE (Se não foi enviada) ---
    # Truque: Em vez de pagar API de Geocoding do Google, olhamos qual o restaurante mais próximo.
    # Assumimos que o usuário está na mesma cidade que o restaurante a 500m dele.
    if not city_slug and lat and lon:
        detect_city_query = text("""
            SELECT r.city_slug 
            FROM restaurants r
            WHERE ST_DWithin(r.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 20000) -- Raio 20km
            ORDER BY ST_Distance(r.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) ASC
            LIMIT 1
        """)
        city_row = (await db.execute(detect_city_query, {"lat": lat, "lon": lon})).mappings().first()
        if city_row and city_row.city_slug:
            city_slug = city_row.city_slug

    # --- 2. ESTRATÉGIA A: CITY_HOME (Curadoria/Destaques) ---
    # Só roda se temos uma cidade definida (enviada ou detectada)
    if city_slug:
        # Normaliza string (sao paulo -> sao_paulo)
        city_norm = city_slug.strip().lower().replace(" ", "_").replace("-", "_")
        
        city_query = text("""
            SELECT 
                o.id, o.restaurant_id, r.name AS restaurant_name, r.logo_url,
                o.title, o.message, o.price_cents, o.original_price_cents, o.end_at,
                0 as distance_m, 'CITY_HOME' as placement
            FROM offers o
            JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.placement = 'CITY_HOME'
              AND o.status = 'ACTIVE'
              AND o.end_at > NOW()
              AND (r.city_slug = :city OR LOWER(r.city) = :city_space)
              AND o.accepted_count < o.accept_limit
            ORDER BY o.created_at DESC
            LIMIT 5
        """)
        
        # Tenta buscar usando slug ("sao_paulo") ou nome com espaço ("sao paulo")
        rows = (await db.execute(city_query, {"city": city_norm, "city_space": city_norm.replace("_", " ")})).mappings().all()
        
        # SE achou ofertas de destaque, retorna elas e ENCERRA AQUI.
        if rows:
            display_name = city_slug.replace('_', ' ').title()
            return {
                "strategy": "CITY_HOME",
                "title": f"Destaques em {display_name}",
                "items": rows
            }
            
        # SE NÃO achou (ex: é uma cidade do interior sem destaques pagos),
        # o código continua para baixo e cai na estratégia de Proximidade (Fallback).

    # --- 3. ESTRATÉGIA B: PROXIMITY (Picks / Interior) ---
    # Busca ofertas ao redor, independentemente de ser destaque ou não.
    
    # 3.1. Tenta buscar convites já gerados (Matches anteriores)
    query_existing = text("""
        SELECT 
            o.id, o.restaurant_id, r.name AS restaurant_name, r.logo_url,
            o.title, o.message, o.price_cents, o.original_price_cents, o.end_at,
            ST_Distance(r.geog, (SELECT geog FROM users WHERE id=:uid))::int as distance_m,
            'NORMAL' as placement
        FROM offer_targets t
        JOIN offers o ON o.id = t.offer_id
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE t.user_id = :uid 
          AND t.used_at IS NULL
          AND o.status = 'ACTIVE'
          AND o.end_at > NOW()
        ORDER BY t.created_at DESC
        LIMIT 5
    """)

    result = await db.execute(query_existing, {"uid": uid})
    rows = result.mappings().all()

    # 3.2. Cold Start / Instant Match (Se não tem nada cacheado)
    if not rows and lat and lon:
        instant_query = text("""
            WITH new_matches AS (
                INSERT INTO offer_targets (user_id, offer_id, released_at)
                SELECT :uid, o.id, NOW()
                FROM offers o
                JOIN restaurants r ON r.id = o.restaurant_id
                WHERE o.status = 'ACTIVE' 
                  AND o.end_at > NOW() 
                  AND o.placement = 'NORMAL' -- Pega ofertas normais
                  AND ST_DWithin(r.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 15000) -- Raio 15km
                ORDER BY ST_Distance(r.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) ASC
                LIMIT 5
                ON CONFLICT DO NOTHING
                RETURNING offer_id
            )
            SELECT 
                o.id, o.restaurant_id, r.name AS restaurant_name, r.logo_url,
                o.title, o.message, o.price_cents, o.original_price_cents, o.end_at,
                ST_Distance(r.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))::int as distance_m,
                'NORMAL' as placement
            FROM new_matches nm
            JOIN offers o ON o.id = nm.offer_id
            JOIN restaurants r ON r.id = o.restaurant_id
        """)
        
        try:
            result = await db.execute(instant_query, {"uid": uid, "lat": lat, "lon": lon})
            await db.commit()
            rows = result.mappings().all()
        except Exception:
            await db.rollback()
            rows = []

    return {
        "strategy": "PROXIMITY",
        "title": "Próximos a Você", # Título genérico para interior/proximidade
        "items": rows
    }


@router.get("/map-source")
async def get_offers_map_source(db: AsyncSession = Depends(get_db_session)):
    """
    Retorna GeoJSON para o Mapa.
    """
    query = text("""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', json_agg(ST_AsGeoJSON(t.*)::json)
        )
        FROM (
            SELECT 
                ST_SetSRID(ST_MakePoint(ST_X(r.geog::geometry), ST_Y(r.geog::geometry)), 4326) as geometry,
                json_build_object(
                    'offer_id', o.id,
                    'title', o.title,
                    'price_cents', o.price_cents,
                    'restaurant_name', r.name,
                    'logo_url', r.logo_url,
                    'type', o.placement, 
                    'color', CASE WHEN o.placement = 'CITY_HOME' THEN '#FFD700' ELSE '#FF5733' END
                ) as properties
            FROM offers o
            JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.status = 'ACTIVE'
              AND o.end_at > NOW()
              AND o.accepted_count < o.accept_limit
        ) as t;
    """)

    result = await db.execute(query)
    geojson_data = result.scalar()

    if not geojson_data:
        return {"type": "FeatureCollection", "features": []}

    return geojson_data


@router.get("/{offer_id}")
async def get_offer_details(
    offer_id: int,
    uid: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Detalhes Completos da Oferta.
    """
    query = text("""
        SELECT 
            o.id, o.title, o.description, o.message, o.price_cents, o.original_price_cents, 
            o.end_at, o.placement,
            r.name as restaurant_name, r.logo_url, r.cover_image_url, 
            r.address_street, r.address_number, r.phone,
            ST_Y(r.geog::geometry) as lat, ST_X(r.geog::geometry) as lon
        FROM offers o
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE o.id = :oid
    """)
    
    row = (await db.execute(query, {"oid": offer_id})).mappings().first()
    
    if not row:
        raise HTTPException(404, "Oferta não encontrada")
        
    return row


# --- WRITE ENDPOINTS (Ações) ---

@router.post("/{offer_id}/accept", response_model=AcceptOfferResponse)
async def accept_offer(
    offer_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    user_id: int = Depends(get_current_user_id),
):
    """
    Botão 'Pegar Oferta'.
    Reserva, gera QR Code (Claim) e atualiza estoque.
    """
    now = datetime.now(timezone.utc)

    # 1. Checagens do Usuário
    user_row = (await db.execute(
        text("SELECT is_blocked, cooldown_until FROM users WHERE id = :uid"),
        {"uid": user_id},
    )).mappings().first()

    if not user_row:
        return AcceptOfferResponse(status="USER_NOT_ELIGIBLE", offer_id=offer_id)
    if user_row["is_blocked"]:
        return AcceptOfferResponse(status="BLOCKED", offer_id=offer_id)
    if user_row["cooldown_until"] is not None and user_row["cooldown_until"] > now:
        return AcceptOfferResponse(status="COOLDOWN", offer_id=offer_id)

    # 2. Checagem da Oferta (Lock de Banco)
    offer = (await db.execute(
        text("""
            SELECT id, status, end_at, accept_limit, accepted_count, accept_ttl_hours
            FROM offers WHERE id = :oid FOR UPDATE
        """),
        {"oid": offer_id},
    )).mappings().first()

    if not offer or offer["status"] != "ACTIVE" or offer["end_at"] <= now:
        return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)

    if int(offer["accepted_count"]) >= int(offer["accept_limit"]):
        return AcceptOfferResponse(status="SOLD_OUT", offer_id=offer_id, accepted_count=offer["accepted_count"], accept_limit=offer["accept_limit"])

    # 3. Checagem de Duplicidade
    existing = (await db.execute(
        text("SELECT status, expires_at, qr_token FROM offer_claims WHERE offer_id = :oid AND user_id = :uid"),
        {"oid": offer_id, "uid": user_id},
    )).mappings().first()

    if existing:
        if existing["status"] == "ACCEPTED":
            return AcceptOfferResponse(
                status="ACCEPTED", offer_id=offer_id, user_id=user_id,
                expires_at=existing["expires_at"], qr_token=existing["qr_token"],
                accepted_count=offer["accepted_count"], accept_limit=offer["accept_limit"]
            )
        return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)

    # 4. Criação do Claim
    ttl = int(offer["accept_ttl_hours"] or 6)
    expires_at = min(offer["end_at"], now + timedelta(hours=ttl))
    qr_token = uuid4()

    await db.execute(
        text("""
            INSERT INTO offer_claims (offer_id, user_id, status, accepted_at, expires_at, qr_token)
            VALUES (:oid, :uid, 'ACCEPTED', :now, :exp, :qr)
        """),
        {"oid": offer_id, "uid": user_id, "now": now, "exp": expires_at, "qr": str(qr_token)}
    )

    # 5. Atualiza Estoque
    await db.execute(text("UPDATE offers SET accepted_count = accepted_count + 1 WHERE id = :oid"), {"oid": offer_id})
    await db.commit()

    # 6. Analytics
    background_tasks.add_task(log_analytics_task, offer_id, user_id, "CLAIM")

    return AcceptOfferResponse(
        status="ACCEPTED",
        offer_id=offer_id,
        user_id=user_id,
        expires_at=expires_at,
        qr_token=str(qr_token),
        accepted_count=offer["accepted_count"] + 1,
        accept_limit=offer["accept_limit"],
    )
