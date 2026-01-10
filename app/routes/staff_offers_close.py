from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])


class CloseOfferRequest(BaseModel):
    reason: str | None = Field(default="MANUAL_CLOSE", max_length=64)


class CloseOfferResponse(BaseModel):
    offer_id: int
    previous_status: str
    status: str
    status_reason: str | None
    closed_at: datetime | None


def _staff_id(staff: dict) -> int | None:
    if "staff_id" in staff:
        return int(staff["staff_id"])
    if "id" in staff:
        return int(staff["id"])
    return None


@router.post("/{offer_id}/close", response_model=CloseOfferResponse)
async def close_offer(
    offer_id: int,
    payload: CloseOfferRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> CloseOfferResponse:
    rid = int(staff["restaurant_id"])
    sid = _staff_id(staff)
    now = datetime.now(timezone.utc)

    # lock para evitar corrida com accept/dispatch etc.
    cur = (await db.execute(
        text("""
            SELECT id, status
            FROM offers
            WHERE id = :oid AND restaurant_id = :rid
            FOR UPDATE
        """),
        {"oid": offer_id, "rid": rid},
    )).mappings().first()

    if not cur:
        raise HTTPException(404, "Offer not found for this restaurant")

    prev_status = str(cur["status"] or "")

    if prev_status not in ("CREATED", "ACTIVE", "PAUSED"):
        raise HTTPException(409, f"Offer cannot be closed from status '{prev_status}'")

    row = (await db.execute(
        text("""
            UPDATE offers
            SET status = 'CLOSED',
                status_reason = :reason,
                status_changed_by_staff_id = :sid,
                closed_at = :now
            WHERE id = :oid AND restaurant_id = :rid
            RETURNING id, status, status_reason, closed_at
        """),
        {
            "oid": offer_id,
            "rid": rid,
            "reason": payload.reason or "MANUAL_CLOSE",
            "sid": sid,
            "now": now,
        },
    )).mappings().first()

    await db.commit()

    return CloseOfferResponse(
        offer_id=int(row["id"]),
        previous_status=prev_status,
        status=str(row["status"]),
        status_reason=row["status_reason"],
        closed_at=row["closed_at"],
    )
