from __future__ import annotations

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])

class RepeatOfferRequest(BaseModel):
    hours_valid: int = Field(12, ge=1, le=72)

class RepeatOfferResponse(BaseModel):
    new_offer_id: int
    from_offer_id: int
    status: str
    created_at: datetime
    end_at: datetime

def _staff_id(staff: dict) -> int | None:
    if "staff_id" in staff: return int(staff["staff_id"])
    if "id" in staff: return int(staff["id"])
    return None

@router.post("/{offer_id}/repeat", response_model=RepeatOfferResponse)
async def repeat_offer(
    offer_id: int,
    payload: RepeatOfferRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> RepeatOfferResponse:
    rid = int(staff["restaurant_id"])
    sid = _staff_id(staff)
    now = datetime.now(timezone.utc)
    end_at = now + timedelta(hours=int(payload.hours_valid))

    src = (await db.execute(
        text("""
            SELECT
              id, restaurant_id,
              title, message, placement, radius_km,
              price_cents, accept_limit, max_target_total, accept_ttl_hours
            FROM offers
            WHERE id = :oid AND restaurant_id = :rid
        """),
        {"oid": offer_id, "rid": rid},
    )).mappings().first()

    if not src:
        raise HTTPException(404, "Offer not found for this restaurant")

    new_id = (await db.execute(
        text("""
            INSERT INTO offers (
              restaurant_id,
              title, message,
              placement, radius_km,
              price_cents,
              accept_limit, accepted_count,
              max_target_total,
              accept_ttl_hours,
              status,
              status_reason,
              status_changed_by_staff_id,
              created_at,
              end_at
            )
            VALUES (
              :rid,
              :title, :message,
              :placement, :radius_km,
              :price_cents,
              :accept_limit, 0,
              :max_target_total,
              :accept_ttl_hours,
              'CREATED',
              'REPEAT',
              :sid,
              :now,
              :end_at
            )
            RETURNING id
        """),
        {
            "rid": rid,
            "title": src["title"],
            "message": src["message"],
            "placement": src["placement"],
            "radius_km": src["radius_km"],
            "price_cents": src["price_cents"],
            "accept_limit": src["accept_limit"],
            "max_target_total": src["max_target_total"],
            "accept_ttl_hours": src["accept_ttl_hours"],
            "sid": sid,
            "now": now,
            "end_at": end_at,
        },
    )).scalar_one()

    await db.commit()

    return RepeatOfferResponse(
        new_offer_id=int(new_id),
        from_offer_id=int(offer_id),
        status="CREATED",
        created_at=now,
        end_at=end_at,
    )
