from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])

Placement = Literal["NORMAL", "CITY_HOME"]

class UpdateCreatedOfferRequest(BaseModel):
    # Permitimos mudar placement também? (eu recomendo NÃO, mas deixei opcional)
    placement: Placement | None = None

    radius_km: int | None = Field(default=None, ge=1, le=50)
    title: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)

    accept_limit: int | None = Field(default=None, ge=1, le=500)
    max_target_total: int | None = Field(default=None, ge=1, le=5000)

    # opcional, caso você use TTL por oferta
    accept_ttl_hours: int | None = Field(default=None, ge=1, le=72)

class UpdateCreatedOfferResponse(BaseModel):
    offer_id: int
    status: str
    placement: str
    radius_km: int | None = None
    title: str | None = None
    message: str | None = None
    accept_limit: int
    max_target_total: int
    accept_ttl_hours: int | None = None

def _staff_id(staff: dict) -> int | None:
    if "staff_id" in staff: return int(staff["staff_id"])
    if "id" in staff: return int(staff["id"])
    return None

@router.patch("/{offer_id}", response_model=UpdateCreatedOfferResponse)
async def update_created_offer(
    offer_id: int,
    payload: UpdateCreatedOfferRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> UpdateCreatedOfferResponse:
    rid = int(staff["restaurant_id"])
    sid = _staff_id(staff)

    # 1) pega oferta e trava
    cur = (await db.execute(
        text("""
            SELECT id, status, placement, radius_km, title, message,
                   accept_limit, max_target_total, accept_ttl_hours
            FROM offers
            WHERE id = :oid AND restaurant_id = :rid
            FOR UPDATE
        """),
        {"oid": offer_id, "rid": rid},
    )).mappings().first()

    if not cur:
        raise HTTPException(404, "Offer not found for this restaurant")

    if (cur["status"] or "") != "CREATED":
        raise HTTPException(409, f"Offer cannot be edited unless status is CREATED (current={cur['status']})")

    # 2) calcula novos valores (patch)
    new_placement = payload.placement or cur["placement"]
    new_radius_km = payload.radius_km if payload.radius_km is not None else cur["radius_km"]

    new_title = payload.title if payload.title is not None else cur["title"]
    new_message = payload.message if payload.message is not None else cur["message"]

    new_accept_limit = int(payload.accept_limit) if payload.accept_limit is not None else int(cur["accept_limit"])
    new_max_target_total = int(payload.max_target_total) if payload.max_target_total is not None else int(cur["max_target_total"])
    new_accept_ttl_hours = payload.accept_ttl_hours if payload.accept_ttl_hours is not None else cur["accept_ttl_hours"]

    # 3) validações por placement
    if new_placement == "NORMAL":
        if new_radius_km is None:
            raise HTTPException(400, "radius_km is required for placement NORMAL")
    elif new_placement == "CITY_HOME":
        # radius pode ser fixo via pricing (20km); se quiser, forçamos NULL/20 aqui
        pass
    else:
        raise HTTPException(400, "Invalid placement")

    # 4) update
    row = (await db.execute(
        text("""
            UPDATE offers
            SET
                placement = :placement,
                radius_km = :radius_km,
                title = :title,
                message = :message,
                accept_limit = :accept_limit,
                max_target_total = :max_target_total,
                accept_ttl_hours = :accept_ttl_hours,
                status_reason = 'MANUAL_EDIT',
                status_changed_by_staff_id = :sid
            WHERE id = :oid AND restaurant_id = :rid AND status = 'CREATED'
            RETURNING id, status, placement, radius_km, title, message,
                      accept_limit, max_target_total, accept_ttl_hours
        """),
        {
            "oid": offer_id,
            "rid": rid,
            "placement": new_placement,
            "radius_km": new_radius_km,
            "title": new_title,
            "message": new_message,
            "accept_limit": new_accept_limit,
            "max_target_total": new_max_target_total,
            "accept_ttl_hours": new_accept_ttl_hours,
            "sid": sid,
        },
    )).mappings().first()

    if not row:
        # raro: alguém mudou status entre SELECT e UPDATE
        await db.rollback()
        raise HTTPException(409, "Offer status changed; try again")

    await db.commit()

    return UpdateCreatedOfferResponse(
        offer_id=int(row["id"]),
        status=str(row["status"]),
        placement=str(row["placement"]),
        radius_km=row["radius_km"],
        title=row["title"],
        message=row["message"],
        accept_limit=int(row["accept_limit"]),
        max_target_total=int(row["max_target_total"]),
        accept_ttl_hours=row["accept_ttl_hours"],
    )
