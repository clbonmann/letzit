from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Literal, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])

# --- CONSTANTES E HELPERS ---

Placement = Literal["NORMAL", "CITY_HOME"]

def _staff_id(staff: dict) -> int | None:
    if "staff_id" in staff: return int(staff["staff_id"])
    if "id" in staff: return int(staff["id"])
    return None

def _normalize_city(s: str) -> str:
    return s.strip().lower().replace(" ", "_").replace("-", "_")

def _utc_day_window(now_utc: datetime) -> tuple[datetime, datetime]:
    start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end

# --- SCHEMAS (MODELOS DE DADOS) ---

# 1. Quote
class QuoteRequest(BaseModel):
    placement: Placement = "NORMAL"
    radius_km: int | None = Field(default=None, ge=1, le=50) # Required for NORMAL
    city: str | None = None  # Required for CITY_HOME if restaurant has no city
    active_minutes: int = Field(30, ge=1, le=240)

class QuoteResponse(BaseModel):
    placement: Placement
    radius_km: int
    price_cents: int
    audience_estimate: int
    # CITY_HOME extras
    city: str | None = None
    max_slots: int | None = None
    used_slots: int | None = None
    available_slots: int | None = None
    status: str | None = None  # AVAILABLE | SOLD_OUT

# 2. Create
class CreateOfferRequest(BaseModel):
    placement: Placement = "NORMAL"
    radius_km: int | None = Field(default=None, ge=1, le=50)
    active_minutes: int = Field(30, ge=1, le=240)
    city: str | None = None
    title: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)
    accept_limit: int = Field(25, ge=1, le=500)
    max_target_total: int = Field(100, ge=1, le=5000)

class CreateOfferResponse(BaseModel):
    offer_id: int
    placement: Placement
    radius_km: int
    price_cents: int
    audience_estimate: int
    city: str | None = None
    slot_status: str | None = None

# 3. Update
class UpdateCreatedOfferRequest(BaseModel):
    placement: Placement | None = None
    radius_km: int | None = Field(default=None, ge=1, le=50)
    title: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)
    accept_limit: int | None = Field(default=None, ge=1, le=500)
    max_target_total: int | None = Field(default=None, ge=1, le=5000)
    accept_ttl_hours: int | None = Field(default=None, ge=1, le=72)

class UpdateCreatedOfferResponse(BaseModel):
    offer_id: int
    status: str
    placement: str
    radius_km: int | None = None
    title: str | None = None
    message: str | None = None
    accept_limit: int
    max_target_total: int
    accept_ttl_hours: int | None = None

# 4. Close & Repeat
class CloseOfferRequest(BaseModel):
    reason: str | None = Field(default="MANUAL_CLOSE", max_length=64)

class CloseOfferResponse(BaseModel):
    offer_id: int
    previous_status: str
    status: str
    status_reason: str | None
    closed_at: datetime | None

class RepeatOfferRequest(BaseModel):
    hours_valid: int = Field(12, ge=1, le=72)

class RepeatOfferResponse(BaseModel):
    new_offer_id: int
    from_offer_id: int
    status: str
    created_at: datetime
    end_at: datetime


# --- ENDPOINTS ---

@router.get("", summary="List Offers")
async def list_staff_offers(
    status: str | None = Query(None),
    placement: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """Lista ofertas do restaurante com filtros."""
    rid = int(staff["restaurant_id"])

    sql = """
        SELECT
            o.id, o.title, o.message, o.placement, o.radius_km,
            o.price_cents, o.status, o.accept_limit, o.accepted_count,
            o.created_at, o.end_at,
            COUNT(c.id) FILTER (WHERE c.status = 'REDEEMED')::int AS redeemed_count,
            COUNT(c.id) FILTER (WHERE c.status = 'NO_SHOW')::int AS no_show_count
        FROM offers o
        LEFT JOIN offer_claims c ON c.offer_id = o.id
        WHERE o.restaurant_id = :rid
    """
    params = {"rid": rid, "limit": limit}

    if status:
        sql += " AND o.status = :status"
        params["status"] = status
    if placement:
        sql += " AND o.placement = :placement"
        params["placement"] = placement

    sql += " GROUP BY o.id ORDER BY o.created_at DESC LIMIT :limit"

    rows = (await db.execute(text(sql), params)).mappings().all()
    return rows


@router.post("/quote", response_model=QuoteResponse, summary="Get Audience & Price Quote")
async def quote_offer(
    payload: QuoteRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """Calcula audiência e preço antes de criar a oferta."""
    rid = int(staff["restaurant_id"])
    active_minutes = int(payload.active_minutes)

    rest = (await db.execute(
        text("SELECT geog, COALESCE(city, '') AS city FROM restaurants WHERE id = :rid"),
        {"rid": rid},
    )).mappings().first()

    if not rest or rest["geog"] is None:
        raise HTTPException(400, "Restaurant location not set (geog is NULL)")

    placement = payload.placement

    # --- Lógica NORMAL ---
    if placement == "NORMAL":
        if payload.radius_km is None:
            raise HTTPException(400, "radius_km is required for NORMAL quote")

        radius_km = int(payload.radius_km)
        radius_m = radius_km * 1000

        price_cents = (await db.execute(
            text("SELECT price_cents FROM pricing_radius WHERE country_code='BR' AND currency='BRL' AND radius_km=:r AND is_active=true"),
            {"r": radius_km},
        )).scalar_one_or_none()

        if price_cents is None:
            raise HTTPException(400, "radius_km not available in pricing_radius")

        audience = (await db.execute(
            text("""
                SELECT COUNT(*)::int FROM users u
                WHERE u.geog IS NOT NULL
                  AND u.last_loc_at > now() - make_interval(mins => :mins)
                  AND ST_DWithin(u.geog, (SELECT geog FROM restaurants WHERE id = :rid), :radius_m)
            """),
            {"rid": rid, "mins": active_minutes, "radius_m": radius_m},
        )).scalar_one()

        return QuoteResponse(
            placement="NORMAL", radius_km=radius_km, price_cents=int(price_cents), audience_estimate=int(audience)
        )

    # --- Lógica CITY_HOME ---
    if placement == "CITY_HOME":
        pricing = (await db.execute(
            text("SELECT radius_km, max_slots, price_cents FROM city_offers_pricing WHERE country_code='BR' AND radius_km=20 AND is_active=true")
        )).mappings().first()

        if not pricing:
            raise HTTPException(400, "city_offers_pricing not configured (radius_km=20)")

        radius_km = int(pricing["radius_km"])
        city = _normalize_city(payload.city or rest["city"])
        if not city:
            raise HTTPException(400, "city is required")

        starts_at, ends_at = _utc_day_window(datetime.now(timezone.utc))
        
        used_slots = (await db.execute(
            text("SELECT COUNT(*)::int FROM city_offer_slots WHERE city=:city AND starts_at=:starts AND ends_at=:ends"),
            {"city": city, "starts": starts_at, "ends": ends_at},
        )).scalar_one()

        available = max(0, int(pricing["max_slots"]) - int(used_slots))
        
        audience = (await db.execute(
            text("""
                SELECT COUNT(*)::int FROM users u
                WHERE u.geog IS NOT NULL
                  AND u.last_loc_at > now() - make_interval(mins => :mins)
                  AND ST_DWithin(u.geog, (SELECT geog FROM restaurants WHERE id = :rid), :radius_m)
            """),
            {"rid": rid, "mins": active_minutes, "radius_m": radius_km * 1000},
        )).scalar_one()

        return QuoteResponse(
            placement="CITY_HOME", radius_km=radius_km, price_cents=int(pricing["price_cents"]),
            audience_estimate=int(audience), city=city, max_slots=int(pricing["max_slots"]),
            used_slots=int(used_slots), available_slots=int(available),
            status="AVAILABLE" if available > 0 else "SOLD_OUT"
        )

    raise HTTPException(400, "Invalid placement")


@router.post("", response_model=CreateOfferResponse, summary="Create Offer")
async def create_offer(
    payload: CreateOfferRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """Cria uma oferta. Se CITY_HOME, aplica travas de slot e concorrência."""
    rid = int(staff["restaurant_id"])
    now = datetime.now(timezone.utc)
    end_at = now + timedelta(hours=12)

    rest = (await db.execute(
        text("SELECT geog, COALESCE(city, '') AS city FROM restaurants WHERE id = :rid"),
        {"rid": rid}
    )).mappings().first()

    if not rest or not rest["geog"]:
        raise HTTPException(400, "Restaurant location missing")

    placement = payload.placement

    # --- Create NORMAL ---
    if placement == "NORMAL":
        if payload.radius_km is None: raise HTTPException(400, "radius_km required")
        radius_km = int(payload.radius_km)
        radius_m = radius_km * 1000
        
        # Copiando lógica exata do quote/create anterior
        price_cents = (await db.execute(
            text("SELECT price_cents FROM pricing_radius WHERE country_code='BR' AND radius_km=:r AND is_active=true"),
            {"r": radius_km}
        )).scalar_one_or_none()
        
        if not price_cents: raise HTTPException(400, "Pricing not found")

        audience = (await db.execute(
            text("""
                SELECT COUNT(*)::int FROM users u
                WHERE u.geog IS NOT NULL
                  AND u.last_loc_at > now() - make_interval(mins => :mins)
                  AND ST_DWithin(u.geog, (SELECT geog FROM restaurants WHERE id=:rid), :radius_m)
            """),
            {"rid": rid, "mins": payload.active_minutes, "radius_m": radius_m}
        )).scalar_one()

        offer_id = (await db.execute(
            text("""
                INSERT INTO offers (restaurant_id, title, message, placement, radius_km, price_cents, accept_limit, max_target_total, created_at, end_at)
                VALUES (:rid, :title, :message, 'NORMAL', :r_km, :price, :lim, :max_tgt, :now, :end)
                RETURNING id
            """),
            {
                "rid": rid, "title": payload.title, "message": payload.message, "r_km": radius_km,
                "price": int(price_cents), "lim": int(payload.accept_limit), "max_tgt": int(payload.max_target_total),
                "now": now, "end": end_at
            }
        )).scalar_one()
        
        await db.commit()
        return CreateOfferResponse(
            offer_id=offer_id, placement="NORMAL", radius_km=radius_km, price_cents=int(price_cents), audience_estimate=int(audience)
        )

    # --- Create CITY_HOME ---
    if placement == "CITY_HOME":
        pricing = (await db.execute(text("SELECT radius_km, max_slots, price_cents FROM city_offers_pricing WHERE country_code='BR' AND radius_km=20 AND is_active=true"))).mappings().first()
        if not pricing: raise HTTPException(400, "Pricing not found")

        city = _normalize_city(payload.city or rest["city"])
        if not city: raise HTTPException(400, "City required")

        # Advisory Lock
        lock_key = f"city_home:{city}"
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": lock_key})

        try:
            used = (await db.execute(
                text("""
                    SELECT COUNT(*)::int FROM offers o
                    JOIN restaurants r ON r.id = o.restaurant_id
                    WHERE o.placement = 'CITY_HOME' AND o.end_at > now() 
                    AND COALESCE(o.status, 'ACTIVE') = 'ACTIVE' AND COALESCE(r.city, '') = :city
                """), {"city": city}
            )).scalar_one()

            if int(used) >= int(pricing["max_slots"]):
                raise HTTPException(409, "SOLD_OUT")

            audience = (await db.execute(
                text("""
                    SELECT COUNT(*)::int FROM users u
                    WHERE u.geog IS NOT NULL
                      AND u.last_loc_at > now() - make_interval(mins => :mins)
                      AND ST_DWithin(u.geog, (SELECT geog FROM restaurants WHERE id=:rid), :radius_m)
                """),
                {"rid": rid, "mins": payload.active_minutes, "radius_m": int(pricing["radius_km"])*1000}
            )).scalar_one()

            offer_id = (await db.execute(
                text("""
                    INSERT INTO offers (restaurant_id, title, message, placement, radius_km, price_cents, accept_limit, max_target_total, created_at, end_at)
                    VALUES (:rid, :title, :message, 'CITY_HOME', :r_km, :price, :lim, :max_tgt, :now, :end)
                    RETURNING id
                """),
                {
                    "rid": rid, "title": payload.title, "message": payload.message, "r_km": int(pricing["radius_km"]),
                    "price": int(pricing["price_cents"]), "lim": int(payload.accept_limit), "max_tgt": int(payload.max_target_total),
                    "now": now, "end": end_at
                }
            )).scalar_one()

            await db.commit()
            return CreateOfferResponse(
                offer_id=offer_id, placement="CITY_HOME", radius_km=int(pricing["radius_km"]), 
                price_cents=int(pricing["price_cents"]), audience_estimate=int(audience), 
                city=city, slot_status="RESERVED"
            )
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, "Collision, try again")
        except Exception:
            await db.rollback()
            raise

    raise HTTPException(400, "Invalid placement")


@router.patch("/{offer_id}", response_model=UpdateCreatedOfferResponse, summary="Update Offer (Created only)")
async def update_created_offer(
    offer_id: int,
    payload: UpdateCreatedOfferRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """Edita oferta APENAS se status='CREATED'. Usa 'FOR UPDATE'."""
    rid = int(staff["restaurant_id"])
    sid = _staff_id(staff)

    cur = (await db.execute(
        text("SELECT id, status, placement, radius_km, title, message, accept_limit, max_target_total, accept_ttl_hours FROM offers WHERE id = :oid AND restaurant_id = :rid FOR UPDATE"),
        {"oid": offer_id, "rid": rid}
    )).mappings().first()

    if not cur: raise HTTPException(404, "Offer not found")
    if (cur["status"] or "") != "CREATED": raise HTTPException(409, "Can only edit CREATED offers")

    # Merge values
    new_placement = payload.placement or cur["placement"]
    new_radius_km = payload.radius_km if payload.radius_km is not None else cur["radius_km"]
    if new_placement == "NORMAL" and new_radius_km is None: raise HTTPException(400, "radius_km required for NORMAL")

    row = (await db.execute(
        text("""
            UPDATE offers SET
                placement = :place, radius_km = :rad, title = :tit, message = :msg,
                accept_limit = :al, max_target_total = :mtt, accept_ttl_hours = :ttl,
                status_reason = 'MANUAL_EDIT', status_changed_by_staff_id = :sid
            WHERE id = :oid AND restaurant_id = :rid AND status = 'CREATED'
            RETURNING id, status, placement, radius_km, title, message, accept_limit, max_target_total, accept_ttl_hours
        """),
        {
            "oid": offer_id, "rid": rid, "place": new_placement, "rad": new_radius_km,
            "tit": payload.title or cur["title"], "msg": payload.message or cur["message"],
            "al": int(payload.accept_limit) if payload.accept_limit else cur["accept_limit"],
            "mtt": int(payload.max_target_total) if payload.max_target_total else cur["max_target_total"],
            "ttl": payload.accept_ttl_hours if payload.accept_ttl_hours is not None else cur["accept_ttl_hours"],
            "sid": sid
        }
    )).mappings().first()
    
    await db.commit()
    return UpdateCreatedOfferResponse(**row)


@router.post("/{offer_id}/close", response_model=CloseOfferResponse, summary="Close Offer")
async def close_offer(
    offer_id: int,
    payload: CloseOfferRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """Encerra manualmente a oferta."""
    rid = int(staff["restaurant_id"])
    sid = _staff_id(staff)
    now = datetime.now(timezone.utc)

    cur = (await db.execute(
        text("SELECT id, status FROM offers WHERE id = :oid AND restaurant_id = :rid FOR UPDATE"),
        {"oid": offer_id, "rid": rid}
    )).mappings().first()

    if not cur: raise HTTPException(404, "Offer not found")
    prev_status = str(cur["status"] or "")
    if prev_status not in ("CREATED", "ACTIVE", "PAUSED"): raise HTTPException(409, f"Cannot close from '{prev_status}'")

    row = (await db.execute(
        text("""
            UPDATE offers SET status = 'CLOSED', status_reason = :reason, status_changed_by_staff_id = :sid, closed_at = :now
            WHERE id = :oid AND restaurant_id = :rid
            RETURNING id, status, status_reason, closed_at
        """),
        {"oid": offer_id, "rid": rid, "reason": payload.reason or "MANUAL_CLOSE", "sid": sid, "now": now}
    )).mappings().first()
    
    await db.commit()
    return CloseOfferResponse(offer_id=int(row["id"]), previous_status=prev_status, status=str(row["status"]), status_reason=row["status_reason"], closed_at=row["closed_at"])


@router.post("/{offer_id}/repeat", response_model=RepeatOfferResponse, summary="Clone Offer")
async def repeat_offer(
    offer_id: int,
    payload: RepeatOfferRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """Clona uma oferta existente."""
    rid = int(staff["restaurant_id"])
    now = datetime.now(timezone.utc)
    end_at = now + timedelta(hours=int(payload.hours_valid))

    src = (await db.execute(
        text("SELECT * FROM offers WHERE id = :oid AND restaurant_id = :rid"),
        {"oid": offer_id, "rid": rid}
    )).mappings().first()

    if not src: raise HTTPException(404, "Source offer not found")

    new_id = (await db.execute(
        text("""
            INSERT INTO offers (
              restaurant_id, title, message, placement, radius_km, price_cents, accept_limit, accepted_count,
              max_target_total, accept_ttl_hours, status, status_reason, status_changed_by_staff_id, created_at, end_at
            ) VALUES (
              :rid, :title, :msg, :place, :rad, :price, :lim, 0, :max_tgt, :ttl, 'CREATED', 'REPEAT', :sid, :now, :end
            ) RETURNING id
        """),
        {
            "rid": rid, "title": src["title"], "msg": src["message"], "place": src["placement"],
            "rad": src["radius_km"], "price": src["price_cents"], "lim": src["accept_limit"],
            "max_tgt": src["max_target_total"], "ttl": src["accept_ttl_hours"],
            "sid": _staff_id(staff), "now": now, "end": end_at
        }
    )).scalar_one()
    
    await db.commit()
    return RepeatOfferResponse(new_offer_id=int(new_id), from_offer_id=int(offer_id), status="CREATED", created_at=now, end_at=end_at)


@router.get("/{offer_id}/eligible-users", summary="Check Eligible Users")
async def eligible_users_for_offer(
    offer_id: int,
    active_minutes: int = Query(30, ge=1, le=240),
    limit: int = Query(5000, ge=1, le=10000),
    exclude_already_targeted: bool = Query(True),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """Lista usuários que podem receber a oferta (Debug/Audience Check)."""
    rid = int(staff["restaurant_id"])
    offer = (await db.execute(
        text("SELECT o.id, o.radius_km, r.geog AS restaurant_geog FROM offers o JOIN restaurants r ON r.id = o.restaurant_id WHERE o.id=:oid AND o.restaurant_id=:rid"),
        {"oid": offer_id, "rid": rid}
    )).mappings().first()

    if not offer or not offer["restaurant_geog"]: raise HTTPException(404, "Offer or location not found")

    radius_m = int(offer["radius_km"]) * 1000
    target_exclusion_sql = "AND NOT EXISTS (SELECT 1 FROM offer_targets t WHERE t.offer_id = :oid AND t.user_id = u.id)" if exclude_already_targeted else ""

    users = (await db.execute(
        text(f"""
            SELECT u.id AS user_id, u.phone_e164, ST_Distance(u.geog, :r_geog)::int AS distance_m
            FROM users u
            WHERE u.geog IS NOT NULL AND u.is_blocked = FALSE AND (u.cooldown_until IS NULL OR u.cooldown_until < now())
            AND u.last_loc_at > (now() - make_interval(mins => :mins)) AND ST_DWithin(u.geog, :r_geog, :radius_m)
            {target_exclusion_sql}
            ORDER BY distance_m ASC LIMIT :limit
        """),
        {"oid": offer_id, "r_geog": offer["restaurant_geog"], "mins": active_minutes, "radius_m": radius_m, "limit": limit}
    )).mappings().all()

    return {"offer_id": offer_id, "total_eligible": len(users), "users": users}
