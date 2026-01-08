from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])

PRICE_TABLE = {
    1: 399,
    2: 599,
    3: 799,
    5: 1199,
    8: 1799,
}

ALLOWED_RADII = sorted(PRICE_TABLE.keys())

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
):
    radius_km = payload.radius_km

    if radius_km not in PRICE_TABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"radius_km must be one of {ALLOWED_RADII}",
        )

    rid = int(staff["restaurant_id"])

    r = (await db.execute(
        text("SELECT geog FROM restaurants WHERE id = :rid"),
        {"rid": rid},
    )).first()

    if not r or r[0] is None:
        raise HTTPException(status_code=400, detail="Restaurant location not set (geog is NULL)")

    radius_m = radius_km * 1000
    active_minutes = payload.active_minutes

    audience = (await db.execute(
        text("""
            SELECT COUNT(*)::int
            FROM users u
            WHERE u.geog IS NOT NULL
              AND u.last_loc_at > now() - (:mins || ' minutes')::interval
              AND ST_DWithin(u.geog, (SELECT geog FROM restaurants WHERE id = :rid), :radius_m)
        """),
        {"rid": rid, "radius_m": radius_m, "mins": active_minutes},
    )).scalar_one()

    return QuoteResponse(
        radius_km=radius_km,
        audience_estimate=int(audience),
        price_cents=int(PRICE_TABLE[radius_km]),
    )
