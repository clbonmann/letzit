from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])

class QuoteRequest(BaseModel):
    radius_km: int = Field(..., ge=1, le=50)
    active_minutes: int = Field(30, ge=1, le=240)

class QuoteResponse(BaseModel):
    radius_km: int
    audience_estimate: int
    price_cents: int

@router.post("/quote", response_model=QuoteResponse)
async def quote_offer(
    payload: QuoteRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> QuoteResponse:
    radius_km = int(payload.radius_km)
    active_minutes = int(payload.active_minutes)
    rid = int(staff["restaurant_id"])

    # 1) buscar preço no BD
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
            detail="radius_km not available in pricing",
        )

    # 2) garantir que restaurante tem geog
    r_geog = (await db.execute(
        text("SELECT geog FROM restaurants WHERE id = :rid"),
        {"rid": rid},
    )).scalar_one_or_none()

    if r_geog is None:
        raise HTTPException(status_code=400, detail="Restaurant location not set (geog is NULL)")

    radius_m = radius_km * 1000

    # 3) audiência por PostGIS
    audience = (await db.execute(
        text("""
            SELECT COUNT(*)::int
            FROM users u
            JOIN restaurants r ON r.id = :rid
            WHERE u.geog IS NOT NULL
              AND r.geog IS NOT NULL
              AND u.last_loc_at > now() - make_interval(mins => :mins)
              AND ST_DWithin(u.geog, r.geog, :radius_m)
        """),
        {"rid": rid, "mins": active_minutes, "radius_m": radius_m},
    )).scalar_one()

    return QuoteResponse(
        radius_km=radius_km,
        audience_estimate=int(audience),
        price_cents=int(price_cents),
    )
