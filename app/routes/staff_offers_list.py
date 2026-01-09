from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])


@router.get("")
async def list_staff_offers(
    status: str | None = Query(None),
    placement: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    rid = int(staff["restaurant_id"])

    sql = """
        SELECT
            o.id,
            o.title,
            o.message,
            o.placement,
            o.radius_km,
            o.price_cents,
            o.status,
            o.accept_limit,
            o.accepted_count,
            o.created_at,
            o.end_at,

            -- métricas
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

    sql += """
        GROUP BY o.id
        ORDER BY o.created_at DESC
        LIMIT :limit
    """

    rows = (await db.execute(text(sql), params)).mappings().all()
    return rows
