from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session

router = APIRouter(prefix="/offers", tags=["offers"])


@router.get("/nearby")
async def offers_nearby(
    radius_km: int = 2,
    limit: int = 50,
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db_session),
):
    if not x_user_id:
        raise HTTPException(401, "X-User-Id header required")

    radius_km = int(radius_km)
    if radius_km < 1 or radius_km > 20:
        raise HTTPException(400, "radius_km must be between 1 and 20")

    limit = int(limit)
    if limit < 1 or limit > 200:
        raise HTTPException(400, "limit must be between 1 and 200")

    u_geog = (await db.execute(
        text("SELECT geog FROM users WHERE id = :uid"),
        {"uid": int(x_user_id)},
    )).scalar_one_or_none()

    if u_geog is None:
        raise HTTPException(400, "User location not set (users.geog is NULL)")

    radius_m = radius_km * 1000

    rows = (
        await db.execute(
            text("""
                SELECT
                o.id,
                o.restaurant_id,
                r.name AS restaurant_name,
                r.city AS restaurant_city,
                o.title,
                o.message,
                o.price_cents,
                o.radius_km,
                o.created_at,
                o.end_at,
                ST_Distance(CAST(:u_geog AS geography), r.geog)::int AS distance_m
            FROM offers o
            JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.placement = 'NORMAL'
              AND o.status = 'ACTIVE'
              AND o.end_at > now()
              AND r.geog IS NOT NULL
              AND ST_DWithin(CAST(:u_geog AS geography), r.geog, :radius_m)
              AND EXISTS (
                SELECT 1
                FROM offer_targets t
                WHERE t.offer_id = o.id
                   AND t.user_id = :uid
                   AND t.released_at IS NOT NULL
                 )
               ORDER BY distance_m ASC, o.created_at DESC
               LIMIT :limit
               """),
            {
            "u_geog": u_geog,
            "radius_m": radius_m,
            "limit": limit,
            "uid": uid,   # 👈 importante
            },
        )
    ).mappings().all()

    return {
        "radius_km": radius_km,
        "count": len(rows),
        "items": rows,
    }
