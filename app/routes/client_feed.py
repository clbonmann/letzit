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
    """Logs analytics events in background without blocking the response."""
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
    city_slug: Optional[str] = Query(None, description="Ex: sao_paulo"),
    uid: int = Depends(get_current_user_id), 
    db: AsyncSession = Depends(get_db_session),
):
    """
    SMART FEED:
    1. If `city_slug` is present -> Returns 'CITY_HOME' (Curated/Fixed offers).
    2. Else -> Returns 'NORMAL' (Proximity/Picks offers).
    3. If Cold Start -> Generates matches instantly.
    """
    
    # Strategy A: CITY_HOME (Curated Fixed List)
    if city_slug:
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
              -- Assuming you store city_slug or normalized city in DB
              AND (r.city = :city OR r.city_slug = :city)
              AND o.accepted_count < o.accept_limit
            ORDER BY o.created_at DESC
            LIMIT 5
        """)
        rows = (await db.execute(city_query, {"city": city_norm})).mappings().all()
        
        if rows:
            return {
                "strategy": "CITY_HOME",
                "title": f"Destaques de {city_slug.replace('_', ' ').title()}",
                "items": rows
            }

    # Strategy B: PROXIMITY (Picks)
    # 1. Try to fetch existing invites
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

    # 2. Cold Start Logic (Instant Match)
    if not rows and lat and lon:
        instant_query = text("""
            WITH new_matches AS (
                INSERT INTO offer_targets (user_id, offer_id, released_at)
                SELECT :uid, o.id, NOW()
                FROM offers o
                JOIN restaurants r ON r.id = o.restaurant_id
                WHERE o.status = 'ACTIVE' AND o.end_at > NOW() AND o.placement = 'NORMAL'
                AND ST_DWithin(r.geog, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 10000)
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
        except Exception as e:
            await db.rollback()
            # Log error
            rows = []

    return {
        "strategy": "PROXIMITY",
        "title": "Escolhidos para Você",
        "items": rows
    }


@router.get("/map-source")
async def get_offers_map_source(db: AsyncSession = Depends(get_db_session)):
    """
    Returns GeoJSON for Map View.
    Includes only ACTIVE offers that are not sold out.
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
    Full Offer Details.
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
        raise HTTPException(404, "Offer not found")
        
    return row


# --- WRITE ENDPOINTS (Actions) ---

@router.post("/{offer_id}/accept", response_model=AcceptOfferResponse)
async def accept_offer(
    offer_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    user_id: int = Depends(get_current_user_id),
):
    """
    The "Grab Deal" Button.
    Reserves the offer, generates a QR Code (Claim), and updates inventory.
    """
    now = datetime.now(timezone.utc)

    # 1. User Safety Checks
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

    # 2. Offer Availability Check (Locking)
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

    # 3. Idempotency Check (Already claimed?)
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

    # 4. Create Claim
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

    # 5. Update Inventory
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
