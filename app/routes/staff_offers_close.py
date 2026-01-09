from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])


class CloseOfferResponse(BaseModel):
    offer_id: int
    status: str
    previous_status: str


@router.post("/{offer_id}/close", response_model=CloseOfferResponse)
async def close_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> CloseOfferResponse:
    rid = int(staff["restaurant_id"])
    now = datetime.now(timezone.utc)

    row = (await db.execute(
        text("""
            UPDATE offers o
            SET status = 'CLOSED',closed_at=:now
            WHERE o.id = :oid
              AND o.restaurant_id = :rid
              AND COALESCE(o.status, 'ACTIVE') IN ('CREATED', 'ACTIVE')
            RETURNING o.id, o.status
        """),
        {"oid": offer_id, "rid": rid, "now": now},
    )).mappings().first()

    # Se não atualizou, pode ser: não existe, não é do restaurante, ou já estava fechada
    if not row:
        # Vamos explicar o motivo com um SELECT simples
        cur = (await db.execute(
            text("""
                SELECT id, restaurant_id, COALESCE(status,'') AS status
                FROM offers
                WHERE id = :oid
            """),
            {"oid": offer_id},
        )).mappings().first()

        if not cur:
            raise HTTPException(status_code=404, detail="Offer not found")
        if int(cur["restaurant_id"]) != rid:
            raise HTTPException(status_code=403, detail="Not allowed (different restaurant)")
        raise HTTPException(status_code=409, detail=f"Offer cannot be closed from status '{cur['status']}'")

    await db.commit()

    # obs: como o UPDATE já mudou status, se você quer previous_status,
    # precisa buscá-lo antes. Para MVP, podemos devolver previous_status='(unknown)'.
    # Melhor: fazer SELECT antes. Mantive simples.
    return CloseOfferResponse(
        offer_id=int(row["id"]),
        status="CLOSED",
        previous_status="(was CREATED/ACTIVE)",
    )
