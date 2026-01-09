from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])


@router.get("/{offer_id}/eligible-users")
async def eligible_users_for_offer(
    offer_id: int,
    active_minutes: int = Query(30, ge=1, le=240),
    limit: int = Query(5000, ge=1, le=20000),
    exclude_already_targeted: bool = Query(True),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    rid = int(staff["restaurant_id"])

    # 1) Confere se a oferta pertence ao restaurante e pega raio + geog do restaurante
    offer = (await db.execute(
        text("""
            SELECT
                o.id,
                o.radius_km,
                o.status,
                r.geog AS r_geog
            FROM offers o
            JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.id = :oid
              AND o.restaurant_id = :rid
        """),
        {"oid": offer_id, "rid": rid},
    )).mappings().first()

    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found for this restaurant")

    if offer["r_geog"] is None:
        raise HTTPException(status_code=400, detail="Restaurant location not set (geog is NULL)")

    if offer["radius_km"] is None:
        raise HTTPException(status_code=400, detail="Offer radius_km is NULL")

    radius_m = int(offer["radius_km"]) * 1000

    # 2) Query elegíveis por raio (ordenado por distância DESC)
    extra_exclude = ""
    if exclude_already_targeted:
        extra_exclude = """
          AND NOT EXISTS (
          SELECT 1
          FROM offer_targets t
          WHERE t.offer_id = :oid
          AND t.user_id = u.id
         )
         """

    rows = (
        await db.execute(
            text(f"""
            SELECT
            u.id AS user_id,
            ST_Distance(
                u.geog,
                (SELECT r.geog FROM restaurants r WHERE r.id = :rid)
            )::int AS distance_m
            FROM users u
            WHERE u.geog IS NOT NULL
            AND u.last_loc_at > now() - make_interval(mins => :mins)
            AND ST_DWithin(
                u.geog,
                (SELECT r.geog FROM restaurants r WHERE r.id = :rid),
                :radius_m
            )
            {extra_exclude}
            ORDER BY distance_m DESC
            LIMIT :limit
           """),
          {
           "oid": offer_id,
           "rid": rid,
           "mins": int(active_minutes),
           "radius_m": radius_m,
           "limit": int(limit),
         },
        )
    ).mappings().all()

    return {
        "offer_id": int(offer_id),
        "radius_km": int(offer["radius_km"]),
        "active_minutes": int(active_minutes),
        "exclude_already_targeted": bool(exclude_already_targeted),
        "count": len(rows),
        "users": rows,  # [{user_id, distance_m}, ...]
    }
