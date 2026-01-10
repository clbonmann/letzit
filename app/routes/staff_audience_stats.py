from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/restaurants", tags=["staff-audience"])


@router.get("/{restaurant_id}/audience-stats")
async def get_audience_stats(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    # Segurança: staff só consulta o próprio restaurante
    rid = int(staff["restaurant_id"])
    if int(restaurant_id) != rid:
        raise HTTPException(status_code=403, detail="Not allowed")

    row = (await db.execute(
        text("""
            SELECT restaurant_id, active_minutes, counts_by_radius, computed_at
            FROM restaurant_audience_cache
            WHERE restaurant_id = :rid
        """),
        {"rid": rid},
    )).mappings().first()

    if not row:
        # cache ainda não gerado pelo cron (primeira execução)
        raise HTTPException(
            status_code=404,
            detail="Audience cache not found yet. Wait for cron job to run.",
        )

    return {
        "restaurant_id": int(row["restaurant_id"]),
        "active_window_minutes": int(row["active_minutes"]),
        "counts_by_radius": row["counts_by_radius"],  # jsonb -> dict
        "computed_at": row["computed_at"].isoformat(),
        "source": "cache",
    }
