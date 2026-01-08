from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])


Placement = Literal["NORMAL", "CITY_HOME"]


class CreateOfferRequest(BaseModel):
    placement: Placement = "NORMAL"

    # NORMAL
    radius_km: int | None = Field(default=None, ge=1, le=50)
    active_minutes: int = Field(30, ge=1, le=240)

    # CITY_HOME (se você não tiver restaurants.city, mande city no payload)
    city: str | None = None  # ex: "sao_paulo"

    # negócio da oferta
    title: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)
    accept_limit: int = Field(25, ge=1, le=500)        # some quando bate accept_limit
    max_target_total: int = Field(100, ge=1, le=5000)  # quantos cupons “disparar”


class CreateOfferResponse(BaseModel):
    offer_id: int
    placement: Placement
    radius_km: int
    price_cents: int
    audience_estimate: int
    city: str | None = None
    slot_status: str | None = None   # só CITY_HOME: RESERVED / SOLD_OUT


def _normalize_city(s: str) -> str:
    return (
        s.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def _utc_day_window(now_utc: datetime) -> tuple[datetime, datetime]:
    # Janela diária UTC (MVP). Depois podemos trocar para America/Sao_Paulo.
    start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


@router.post("", response_model=CreateOfferResponse)
async def create_offer(
    payload: CreateOfferRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> CreateOfferResponse:
    rid = int(staff["restaurant_id"])
    now = datetime.now(timezone.utc)
    end_offer = now + timedelta(hours=12)
    # 1) Restaurante precisa ter geog
    rest = (await db.execute(
        text("""
            SELECT id, geog, COALESCE(city, '') AS city
            FROM restaurants
            WHERE id = :rid
        """),
        {"rid": rid},
    )).mappings().first()

    if not rest:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    if rest["geog"] is None:
        raise HTTPException(status_code=400, detail="Restaurant location not set (geog is NULL)")

    placement: Placement = payload.placement

    # -----------------------
    # NORMAL (por raio)
    # -----------------------
    if placement == "NORMAL":
        if payload.radius_km is None:
            raise HTTPException(status_code=400, detail="radius_km is required for NORMAL offers")

        radius_km = int(payload.radius_km)
        radius_m = radius_km * 1000
        active_minutes = int(payload.active_minutes)

        # 2) Preço do BD
        price_cents = (await db.execute(
            text("""
                SELECT price_cents
                FROM pricing_radius
                WHERE country_code = :cc
                  AND currency = :cur
                  AND radius_km = :radius_km
                  AND is_active = true
            """),
            {"cc": "BR", "cur": "BRL", "radius_km": radius_km},
        )).scalar_one_or_none()

        if price_cents is None:
            raise HTTPException(status_code=400, detail="radius_km not available in pricing")

        # 3) Audiência (PostGIS)
        audience = (await db.execute(
            text("""
                SELECT COUNT(*)::int
                FROM users u
                WHERE u.geog IS NOT NULL
                  AND u.last_loc_at > now() - make_interval(mins => :mins)
                  AND ST_DWithin(u.geog, (SELECT geog FROM restaurants WHERE id = :rid), :radius_m)
            """),
            {"rid": rid, "mins": active_minutes, "radius_m": radius_m},
        )).scalar_one()

        # 4) Cria offer
        offer_id = (await db.execute(
           text("""
               INSERT INTO offers (
                restaurant_id,
                title,
                message,
                placement,
                radius_km,
                price_cents,
                accept_limit,
                max_target_total,
                created_at,
                end_at
           )
           VALUES (
             :rid,
             :title,
             :message,
             :placement,
             :radius_km,
             :price_cents,
             :accept_limit,
             :max_target_total,
             :now
             :end_offer
           )
           RETURNING id
           """),
        {
           "rid": rid,
           "title": payload.title,
           "message": payload.message,
           "placement": placement,
           "radius_km": radius_km,
           "price_cents": int(price_cents),
           "accept_limit": int(payload.accept_limit),
           "max_target_total": int(payload.max_target_total),
           "now": now,
           "end_offer": end_offer,
        },
    )).scalar_one()

        await db.commit()

        return CreateOfferResponse(
            offer_id=int(row),
            placement="NORMAL",
            radius_km=radius_km,
            price_cents=int(price_cents),
            audience_estimate=int(audience),
        )

    # -----------------------
    # CITY_HOME (20km + 5 slots por cidade)
    # -----------------------
    if placement == "CITY_HOME":
        # 1) raio e pricing do BD
        pricing = (await db.execute(
            text("""
                SELECT radius_km, max_slots, price_cents
                FROM city_offers_pricing
                WHERE country_code = :cc
                  AND currency = :cur
                  AND radius_km = 20
                  AND is_active = true
            """),
            {"cc": "BR", "cur": "BRL"},
        )).mappings().first()

        if not pricing:
            raise HTTPException(status_code=400, detail="city_offers_pricing not configured for radius_km=20")

        radius_km = int(pricing["radius_km"])  # 20
        radius_m = radius_km * 1000
        max_slots = int(pricing["max_slots"])
        price_cents = int(pricing["price_cents"])

        # 2) cidade
        city = payload.city or rest["city"]
        if not city:
            raise HTTPException(status_code=400, detail="city is required (payload.city or restaurants.city)")
        city = _normalize_city(city)

        # 3) janela (diária UTC)
        starts_at, ends_at = _utc_day_window(now)

        # 4) Lock por cidade+janela pra evitar corrida (último slot)
        lock_key = f"city_home:{city}:{starts_at.isoformat()}:{ends_at.isoformat()}"
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": lock_key})

        try:
            async with db.begin():  # transação
                # 5) checa slots usados
                used = (await db.execute(
                    text("""
                        SELECT COUNT(*)::int
                        FROM city_offer_slots
                        WHERE city = :city
                          AND starts_at = :starts
                          AND ends_at = :ends
                    """),
                    {"city": city, "starts": starts_at, "ends": ends_at},
                )).scalar_one()

                if int(used) >= max_slots:
                    raise HTTPException(status_code=409, detail="SOLD_OUT")

                # 6) audiência (20km, mais “cidade inteira”)
                active_minutes = int(payload.active_minutes)
                audience = (await db.execute(
                    text("""
                        SELECT COUNT(*)::int
                        FROM users u
                        WHERE u.geog IS NOT NULL
                          AND u.last_loc_at > now() - make_interval(mins => :mins)
                          AND ST_DWithin(u.geog, (SELECT geog FROM restaurants WHERE id = :rid), :radius_m)
                    """),
                    {"rid": rid, "mins": active_minutes, "radius_m": radius_m},
                )).scalar_one()

                # 7) cria offer
                offer_id = (await db.execute(
                    text("""
                        INSERT INTO offers (
                            restaurant_id, placement, radius_km, price_cents,
                            audience_estimate, title, message, accept_limit, max_target_total,
                            created_at
                        )
                        VALUES (
                            :rid, 'CITY_HOME', :radius_km, :price_cents,
                            :aud, :title, :message, :accept_limit, :max_target_total,
                            :now
                        )
                        RETURNING id
                    """),
                    {
                        "rid": rid,
                        "radius_km": radius_km,
                        "price_cents": price_cents,
                        "aud": int(audience),
                        "title": payload.title,
                        "message": payload.message,
                        "accept_limit": int(payload.accept_limit),
                        "max_target_total": int(payload.max_target_total),
                        "now": now,
                    },
                )).scalar_one()

                # 8) reserva slot
                await db.execute(
                    text("""
                        INSERT INTO city_offer_slots (
                            city, starts_at, ends_at,
                            offer_id, restaurant_id, price_cents
                        )
                        VALUES (
                            :city, :starts, :ends,
                            :offer_id, :rid, :price_cents
                        )
                    """),
                    {
                        "city": city,
                        "starts": starts_at,
                        "ends": ends_at,
                        "offer_id": int(offer_id),
                        "rid": rid,
                        "price_cents": price_cents,
                    },
                )

            # begin() commita automaticamente se não houver exception

        except HTTPException:
            # repassa SOLD_OUT etc.
            raise
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Slot collision (try again)")

        return CreateOfferResponse(
            offer_id=int(offer_id),
            placement="CITY_HOME",
            radius_km=radius_km,
            price_cents=price_cents,
            audience_estimate=int(audience),
            city=city,
            slot_status="RESERVED",
        )

    raise HTTPException(status_code=400, detail="Invalid placement")
