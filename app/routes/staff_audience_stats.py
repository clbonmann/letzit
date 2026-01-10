from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.jobs.audience_cache import refresh_restaurant_audience_cache

router = APIRouter(prefix="/staff/restaurants", tags=["staff-audience"])

@router.get("/{restaurant_id}/audience-stats")
async def get_audience_stats(
    restaurant_id: int,
    auto_refresh_if_stale: bool = Query(True),
    max_age_seconds: int = Query(240, ge=30, le=3600),  # stale se > 4 min (job é 3 min)
    active_minutes: int = Query(30, ge=1, le=240),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    # segurança: staff só vê o próprio restaurante
    rid = int(staff["restaurant_id"])
    if int(restaurant_id) != rid:
        raise HTTPException(status_code=403, detail="Not allowed")

    cached = (await db.execute(
        text("""
            SELECT restaurant_id, active_minutes, counts_by_radius, computed_at
            FROM restaurant_audience_cache
            WHERE restaurant_id = :rid
        """),
        {"rid": rid},
    )).mappings().first()

    # Se não tem cache ainda, calcula na hora (primeiro acesso)
    if not cached:
        try:
            return await refresh_restaurant_audience_cache(db, restaurant_id=rid, active_minutes=active_minutes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Opcional: refresh se stale
    if auto_refresh_if_stale:
        is_stale = (await db.execute(
            text("SELECT (EXTRACT(EPOCH FROM (now() - :t)))::int AS age_s"),
            {"t": cached["computed_at"]},
        )).mappings().first()
        age_s = int(is_stale["age_s"])

        if age_s > int(max_age_seconds) or int(cached["active_minutes"]) != int(active_minutes):
            try:
                return await refresh_restaurant_audience_cache(db, restaurant_id=rid, active_minutes=active_minutes)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

    return {
        "restaurant_id": int(cached["restaurant_id"]),
        "active_minutes": int(cached["active_minutes"]),
        "counts_by_radius": cached["counts_by_radius"],
        "computed_at": cached["computed_at"].isoformat(),
        "source": "cache",
    }
