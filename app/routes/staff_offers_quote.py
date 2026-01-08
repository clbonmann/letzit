from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])


Placement = Literal["NORMAL", "CITY_HOME"]


class QuoteRequest(BaseModel):
    placement: Placement = "NORMAL"

    # NORMAL
    radius_km: int | None = Field(default=None, ge=1, le=50)

    # CITY_HOME (se não tiver restaurants.city, mande via payload)
    city: str | None = None  # ex: "sao_paulo"

    # audiência
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


def _normalize_city(s: str) -> str:
    return (
        s.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def _utc_day_window(now_utc: datetime) -> tuple[datetime, datetime]:
    start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


@router.post("/quote", response_model=QuoteResponse)
async def quote_offer(
    payload: QuoteRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> QuoteResponse:
    rid = int(staff["restaurant_id"])
    now = datetime.now(timezone.utc)
    active_minutes = int(payload.active_minutes)

    # Restaurante precisa ter geog
    rest = (await db.execute(
        text("SELECT geog, COALESCE(city, '') AS city FROM restaurants WHERE id = :rid"),
        {"rid": rid},
    )).mappings().first()

    if not rest or rest["geog"] is None:
        raise HTTPException(status_code=400, detail="Restaurant location not set (geog is NULL)")

    placement: Placement = payload.placement

    # -----------------------
    # NORMAL (por raio)
    # -----------------------
    if placement == "NORMAL":
        if payload.radius_km is None:
            raise HTTPException(status_code=400, detail="radius_km is required for NORMAL quote")

        radius_km = int(payload.radius_km)
        radius_m = radius_km * 1000

        # preço vem do BD
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="radius_km not available in pricing_radius",
            )

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

        return QuoteResponse(
            placement="NORMAL",
            radius_km=radius_km,
            price_cents=int(price_cents),
            audience_estimate=int(audience),
        )

    # -----------------------
    # CITY_HOME (20km, slots limitados)
    # -----------------------
    if placement == "CITY_HOME":
        # pricing do BD (fixo 20km por enquanto)
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
            raise HTTPException(status_code=400, detail="city_offers_pricing not configured (radius_km=20)")

        radius_km = int(pricing["radius_km"])  # 20
        radius_m = radius_km * 1000
        max_slots = int(pricing["max_slots"])
        price_cents = int(pricing["price_cents"])

        city = payload.city or rest["city"]
        if not city:
            raise HTTPException(status_code=400, detail="city is required (payload.city or restaurants.city)")
        city = _normalize_city(city)

        starts_at, ends_at = _utc_day_window(now)

        # slots usados na janela
        used_slots = (await db.execute(
            text("""
                SELECT COUNT(*)::int
                FROM city_offer_slots
                WHERE city = :city
                  AND starts_at = :starts
                  AND ends_at = :ends
            """),
            {"city": city, "starts": starts_at, "ends": ends_at},
        )).scalar_one()

        available = max(0, max_slots - int(used_slots))

        # audiência (20km)
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

        return QuoteResponse(
            placement="CITY_HOME",
            radius_km=radius_km,
            price_cents=price_cents,
            audience_estimate=int(audience),
            city=city,
            max_slots=max_slots,
            used_slots=int(used_slots),
            available_slots=int(available),
            status="AVAILABLE" if available > 0 else "SOLD_OUT",
        )

    raise HTTPException(status_code=400, detail="Invalid placement")
