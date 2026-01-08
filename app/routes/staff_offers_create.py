from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
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

    # CITY_HOME (se restaurants.city estiver vazio, você pode mandar no payload)
    city: str | None = None

    # oferta
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
    slot_status: str | None = None  # CITY_HOME: RESERVED / SOLD_OUT


def _normalize_city(s: str) -> str:
    return s.strip().lower().replace(" ", "_").replace("-", "_")


@router.post("", response_model=CreateOfferResponse)
async def create_offer(
    payload: CreateOfferRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> CreateOfferResponse:
    rid = int(staff["restaurant_id"])
    now = datetime.now(timezone.utc)
    end_offer = now + timedelta(hours=12)

    # Restaurante precisa ter geog (e idealmente city)
    rest = (
        await db.execute(
            text("""
                SELECT geog, COALESCE(city, '') AS city
                FROM restaurants
                WHERE id = :rid
            """),
            {"rid": rid},
        )
    ).mappings().first()

    if not rest:
        raise HTTPException(404, "Restaurant not found")

    if rest["geog"] is None:
        raise HTTPException(400, "Restaurant location not set (geog is NULL)")

    placement: Placement = payload.placement

    # =====================================================
    # NORMAL (por raio)
    # =====================================================
    if placement == "NORMAL":
        if payload.radius_km is None:
            raise HTTPException(400, "radius_km is required for NORMAL")

        radius_km = int(payload.radius_km)
        radius_m = radius_km * 1000
        active_minutes = int(payload.active_minutes)

        price_cents = (
            await db.execute(
                text("""
                    SELECT price_cents
                    FROM pricing_radius
                    WHERE country_code='BR'
                      AND currency='BRL'
                      AND radius_km=:r
                      AND is_active=true
                """),
                {"r": radius_km},
            )
        ).scalar_one_or_none()

        if price_cents is None:
            raise HTTPException(400, "radius_km not available in pricing_radius")

        audience = (
            await db.execute(
                text("""
                    SELECT COUNT(*)::int
                    FROM users u
                    WHERE u.geog IS NOT NULL
                      AND u.last_loc_at > now() - make_interval(mins => :mins)
                      AND ST_DWithin(
                        u.geog,
                        (SELECT geog FROM restaurants WHERE id=:rid),
                        :radius_m
                      )
                """),
                {"rid": rid, "mins": active_minutes, "radius_m": radius_m},
            )
        ).scalar_one()

        offer_id = (
            await db.execute(
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
                        'NORMAL',
                        :radius_km,
                        :price_cents,
                        :accept_limit,
                        :max_target_total,
                        :now,
                        :end_offer
                    )
                    RETURNING id
                """),
                {
                    "rid": rid,
                    "title": payload.title,
                    "message": payload.message,
                    "radius_km": radius_km,
                    "price_cents": int(price_cents),
                    "accept_limit": int(payload.accept_limit),
                    "max_target_total": int(payload.max_target_total),
                    "now": now,
                    "end_offer": end_offer,
                },
            )
        ).scalar_one()

        await db.commit()

        return CreateOfferResponse(
            offer_id=int(offer_id),
            placement="NORMAL",
            radius_km=radius_km,
            price_cents=int(price_cents),
            audience_estimate=int(audience),
        )

    # =====================================================
    # CITY_HOME (rolling 5 sempre por cidade)
    # =====================================================
    if placement == "CITY_HOME":
        # Pricing do BD (fixo 20km e 5 slots, mas configurável no DB)
        pricing = (
            await db.execute(
                text("""
                    SELECT radius_km, max_slots, price_cents
                    FROM city_offers_pricing
                    WHERE country_code='BR'
                      AND currency='BRL'
                      AND radius_km=20
                      AND is_active=true
                """)
            )
        ).mappings().first()

        if not pricing:
            raise HTTPException(400, "city_offers_pricing not configured (radius_km=20)")

        radius_km = int(pricing["radius_km"])  # 20
        radius_m = radius_km * 1000
        max_slots = int(pricing["max_slots"])  # 5
        price_cents = int(pricing["price_cents"])  # 2999

        # Cidade: payload.city override, senão restaurants.city
        city = payload.city or rest["city"]
        if not city:
            raise HTTPException(400, "city is required (payload.city or restaurants.city)")
        city = _normalize_city(city)

        # Lock por cidade pra evitar corrida ao ocupar último slot
        lock_key = f"city_home:{city}"
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": lock_key})

        try:
            # Conta quantas CITY_HOME ativas existem AGORA nessa cidade
            used = (
                await db.execute(
                    text("""
                        SELECT COUNT(*)::int
                        FROM offers o
                        JOIN restaurants r ON r.id = o.restaurant_id
                        WHERE o.placement = 'CITY_HOME'
                          AND o.end_offer > now()
                          AND COALESCE(o.status, 'ACTIVE') = 'ACTIVE'
                          AND COALESCE(r.city, '') = :city
                    """),
                    {"city": city},
                )
            ).scalar_one()

            if int(used) >= max_slots:
                await db.rollback()
                raise HTTPException(409, "SOLD_OUT")

            # Audiência (20km, últimos N minutos)
            active_minutes = int(payload.active_minutes)
            audience = (
                await db.execute(
                    text("""
                        SELECT COUNT(*)::int
                        FROM users u
                        WHERE u.geog IS NOT NULL
                          AND u.last_loc_at > now() - make_interval(mins => :mins)
                          AND ST_DWithin(
                            u.geog,
                            (SELECT geog FROM restaurants WHERE id=:rid),
                            :radius_m
                          )
                    """),
                    {"rid": rid, "mins": active_minutes, "radius_m": radius_m},
                )
            ).scalar_one()

            offer_id = (
                await db.execute(
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
                            'CITY_HOME',
                            :radius_km,
                            :price_cents,
                            :accept_limit,
                            :max_target_total,
                            :now,
                            :end_offer
                        )
                        RETURNING id
                    """),
                    {
                        "rid": rid,
                        "title": payload.title,
                        "message": payload.message,
                        "radius_km": radius_km,
                        "price_cents": price_cents,
                        "accept_limit": int(payload.accept_limit),
                        "max_target_total": int(payload.max_target_total),
                        "now": now,
                        "end_offer": end_offer,
                    },
                )
            ).scalar_one()

            await db.commit()

            return CreateOfferResponse(
                offer_id=int(offer_id),
                placement="CITY_HOME",
                radius_km=radius_km,
                price_cents=price_cents,
                audience_estimate=int(audience),
                city=city,
                slot_status="RESERVED",
            )

        except HTTPException:
            raise
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, "Collision, try again")
        except Exception:
            await db.rollback()
            raise

    raise HTTPException(400, "Invalid placement")
