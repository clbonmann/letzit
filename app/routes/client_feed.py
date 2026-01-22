from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session, AsyncSessionLocal
from app.deps_client import get_current_client_id
# IMPORTANDO SCHEMAS
from app.schemas.client import AcceptOfferResponse

router = APIRouter(prefix="/client/offers", tags=["client-feed"])

async def log_analytics_task(offer_id: int, client_id: int, event: str):
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                text("INSERT INTO offer_analytics (offer_id, client_id, event_type) VALUES (:oid, :uid, :evt)"),
                {"oid": offer_id, "uid": client_id, "evt": event}
            )
            await session.commit()
        except Exception as e: print(f"Analytics error: {e}")

@router.get("/picks")
async def get_picks(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    city_slug: Optional[str] = Query(None),
    uid: int = Depends(get_current_client_id), 
    db: AsyncSession = Depends(get_db_session),
):
    # 1. Auto-detecção de cidade
    if not city_slug and lat and lon:
        res = (await db.execute(
            text("SELECT city_slug FROM restaurants WHERE ST_DWithin(geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 20000) ORDER BY geog <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) LIMIT 1"),
            {"lat": lat, "lon": lon}
        )).mappings().first()
        if res and res.city_slug: city_slug = res.city_slug

    # 2. Estratégia CITY_HOME
    if city_slug:
        city_norm = city_slug.strip().lower().replace(" ", "_").replace("-", "_")
        rows = (await db.execute(
            text("""
                SELECT o.id, o.restaurant_id, r.name AS restaurant_name, r.logo_url, o.title, o.message, o.price_cents, o.original_price_cents, o.end_at, 0 as distance_m, 'CITY_HOME' as placement
                FROM offers o JOIN restaurants r ON r.id = o.restaurant_id
                WHERE o.placement = 'CITY_HOME' AND o.status = 'ACTIVE' AND o.end_at > NOW() AND (r.city_slug = :city OR LOWER(r.city) = :city_sp) AND o.accepted_count < o.accept_limit
                ORDER BY o.created_at DESC LIMIT 5
            """), {"city": city_norm, "city_sp": city_norm.replace("_", " ")}
        )).mappings().all()
        if rows:
            return {"strategy": "CITY_HOME", "title": f"Destaques em {city_slug.replace('_', ' ').title()}", "items": rows}

    # 3. Estratégia PROXIMITY
    rows = (await db.execute(
        text("""
            SELECT o.id, o.restaurant_id, r.name AS restaurant_name, r.logo_url, o.title, o.message, o.price_cents, o.original_price_cents, o.end_at, ST_Distance(r.geog, (SELECT geog FROM clients WHERE id=:uid))::int as distance_m, 'NORMAL' as placement
            FROM offer_targets t JOIN offers o ON o.id = t.offer_id JOIN restaurants r ON r.id = o.restaurant_id
            WHERE t.client_id = :uid AND t.used_at IS NULL AND o.status = 'ACTIVE' AND o.end_at > NOW()
            ORDER BY t.created_at DESC LIMIT 5
        """), {"uid": uid}
    )).mappings().all()

    # Cold Start
    if not rows and lat and lon:
        try:
            rows = (await db.execute(
                text("""
                    WITH new_matches AS (
                        INSERT INTO offer_targets (client_id, offer_id, released_at)
                        SELECT :uid, o.id, NOW() FROM offers o JOIN restaurants r ON r.id = o.restaurant_id
                        WHERE o.status = 'ACTIVE' AND o.end_at > NOW() AND o.placement = 'NORMAL' AND ST_DWithin(r.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 15000)
                        ORDER BY ST_Distance(r.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) ASC LIMIT 5
                        ON CONFLICT DO NOTHING RETURNING offer_id
                    )
                    SELECT o.id, o.restaurant_id, r.name AS restaurant_name, r.logo_url, o.title, o.message, o.price_cents, o.original_price_cents, o.end_at, ST_Distance(r.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))::int as distance_m, 'NORMAL' as placement
                    FROM new_matches nm JOIN offers o ON o.id = nm.offer_id JOIN restaurants r ON r.id = o.restaurant_id
                """), {"uid": uid, "lat": lat, "lon": lon}
            )).mappings().all()
            await db.commit()
        except Exception:
            await db.rollback()
            rows = []

    return {"strategy": "PROXIMITY", "title": "Próximos a Você", "items": rows}

@router.get("/map-source")
async def get_offers_map_source(db: AsyncSession = Depends(get_db_session)):
    query = text("""
        SELECT json_build_object('type', 'FeatureCollection', 'features', json_agg(ST_AsGeoJSON(t.*)::json))
        FROM (
            SELECT ST_SetSRID(ST_MakePoint(ST_X(r.geog::geometry), ST_Y(r.geog::geometry)), 4326) as geometry,
            json_build_object('offer_id', o.id, 'title', o.title, 'price_cents', o.price_cents, 'restaurant_name', r.name, 'logo_url', r.logo_url, 'type', o.placement) as properties
            FROM offers o JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.status = 'ACTIVE' AND o.end_at > NOW() AND o.accepted_count < o.accept_limit
        ) as t;
    """)
    res = (await db.execute(query)).scalar()
    return res if res else {"type": "FeatureCollection", "features": []}

@router.get("/{offer_id}")
async def get_offer_details(offer_id: int, uid: int = Depends(get_current_client_id), db: AsyncSession = Depends(get_db_session)):
    row = (await db.execute(
        text("SELECT o.id, o.title, o.description, o.message, o.price_cents, o.original_price_cents, o.end_at, o.placement, r.name as restaurant_name, r.logo_url, r.cover_image_url, r.address_street, r.address_number, r.phone, ST_Y(r.geog::geometry) as lat, ST_X(r.geog::geometry) as lon FROM offers o JOIN restaurants r ON r.id = o.restaurant_id WHERE o.id = :oid"),
        {"oid": offer_id}
    )).mappings().first()
    if not row: raise HTTPException(404, "Oferta não encontrada")
    return row

@router.post("/{offer_id}/accept", response_model=AcceptOfferResponse)
async def accept_offer(offer_id: int, bg: BackgroundTasks, db: AsyncSession = Depends(get_db_session), uid: int = Depends(get_current_client_id)):
    now = datetime.now(timezone.utc)
    # Checks
    u = (await db.execute(text("SELECT is_blocked, cooldown_until FROM clients WHERE id=:uid"), {"uid": uid})).mappings().first()
    if not u: return AcceptOfferResponse(status="client_NOT_ELIGIBLE", offer_id=offer_id)
    if u.is_blocked: return AcceptOfferResponse(status="BLOCKED", offer_id=offer_id)
    if u.cooldown_until and u.cooldown_until > now: return AcceptOfferResponse(status="COOLDOWN", offer_id=offer_id)
    
    # Offer Lock
    o = (await db.execute(text("SELECT id, status, end_at, accept_limit, accepted_count, accept_ttl_hours FROM offers WHERE id=:oid FOR UPDATE"), {"oid": offer_id})).mappings().first()
    if not o or o.status != "ACTIVE" or o.end_at <= now: return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)
    if o.accepted_count >= o.accept_limit: return AcceptOfferResponse(status="SOLD_OUT", offer_id=offer_id, accepted_count=o.accepted_count, accept_limit=o.accept_limit)
    
    # Existing
    ex = (await db.execute(text("SELECT status, expires_at, qr_token FROM offer_claims WHERE offer_id=:oid AND client_id=:uid"), {"oid": offer_id, "uid": uid})).mappings().first()
    if ex: return AcceptOfferResponse(status="ACCEPTED" if ex.status=="ACCEPTED" else "CLOSED", offer_id=offer_id, expires_at=ex.expires_at, qr_token=ex.qr_token, accepted_count=o.accepted_count, accept_limit=o.accept_limit)

    # Claim
    ttl = o.accept_ttl_hours or 6
    exp = min(o.end_at, now + timedelta(hours=ttl))
    qr = str(uuid4())
    await db.execute(text("INSERT INTO offer_claims (offer_id, client_id, status, accepted_at, expires_at, qr_token) VALUES (:oid, :uid, 'ACCEPTED', :now, :exp, :qr)"), {"oid": offer_id, "uid": uid, "now": now, "exp": exp, "qr": qr})
    await db.execute(text("UPDATE offers SET accepted_count = accepted_count + 1 WHERE id = :oid"), {"oid": offer_id})
    await db.commit()
    
    bg.add_task(log_analytics_task, offer_id, uid, "CLAIM")
    return AcceptOfferResponse(status="ACCEPTED", offer_id=offer_id, client_id=uid, expires_at=exp, qr_token=qr, accepted_count=o.accepted_count+1, accept_limit=o.accept_limit)

@router.get("/restaurants")
async def get_restaurants_list(
    lat: float,
    long: float, # O Frontend envia 'long', então renomeamos aqui para bater
    page: int = 1,
    limit: int = 10, # Mudamos o padrão para 10 conforme seu pedido
    db: AsyncSession = Depends(get_db_session)
):
    """
    Lista restaurantes ordenados por distância num raio de 20km.
    """
    offset = (page - 1) * limit
    
    # PostGIS:
    # 1. ST_Distance: Calcula a distância para ordenar e exibir.
    # 2. ST_DWithin: Filtra quem está DENTRO de 20.000 metros (WHERE clause).
    query = text("""
        SELECT 
            id, 
            name, 
            logo_url, 
            cover_image_url, 
            city, 
            address, -- Adicionei address pois o frontend usa
            reputation, -- O frontend usa para mostrar as estrelinhas
            ST_Distance(geog, ST_SetSRID(ST_MakePoint(:long, :lat), 4326))::int as distance_meters
        FROM restaurants
        WHERE is_active = TRUE
          AND ST_DWithin(geog, ST_SetSRID(ST_MakePoint(:long, :lat), 4326), 20000) -- FILTRO DE 20KM
        ORDER BY distance_meters ASC
        LIMIT :limit OFFSET :offset
    """)
    
    rows = (await db.execute(query, {
        "lat": lat, 
        "long": long, 
        "limit": limit, 
        "offset": offset
    })).mappings().all()
    
    return rows

@router.get("/my-claims")
async def get_my_claims(
    uid: int = Depends(get_current_client_id), 
    db: AsyncSession = Depends(get_db_session)
):
    """
    Retorna os cupons ATIVOS do usuário (Status 'ACCEPTED').
    """
    query = text("""
        SELECT 
            c.id as claim_id,
            c.qr_token,
            c.expires_at,
            c.status,
            o.title,
            r.name as restaurant_name,
            r.logo_url
        FROM offer_claims c
        JOIN offers o ON o.id = c.offer_id
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE c.client_id = :uid 
        AND c.status = 'ACCEPTED'
        AND c.expires_at > NOW()
        ORDER BY c.expires_at ASC
    """)
    
    rows = (await db.execute(query, {"uid": uid})).mappings().all()
    return rows