from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.schemas.offers import AcceptOfferResponse
from app.settings import settings  # ajuste se o seu settings.py tiver outro path

router = APIRouter(prefix="/staff/debug", tags=["staff-debug"])


class AcceptAsUserRequest(BaseModel):
    user_id: int = Field(..., ge=1)


@router.post("/offers/{offer_id}/accept-as-user", response_model=AcceptOfferResponse)
async def accept_offer_as_user(
    offer_id: int,
    payload: AcceptAsUserRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> AcceptOfferResponse:
    # 0) HARD BLOCK em produção
    # Ajuste conforme seu padrão de ENV/DEBUG
    #if getattr(settings, "ENV", "prod") == "prod":
    #    raise HTTPException(status_code=403, detail="Debug endpoint disabled in production")

    rid = int(staff["restaurant_id"])
    user_id = int(payload.user_id)
    now = datetime.now(timezone.utc)

    # 1) user check
    user_row = (await db.execute(
        text("SELECT is_blocked, cooldown_until FROM users WHERE id = :uid"),
        {"uid": user_id},
    )).mappings().first()

    if not user_row:
        return AcceptOfferResponse(status="USER_NOT_ELIGIBLE", offer_id=offer_id)

    if user_row["is_blocked"]:
        return AcceptOfferResponse(status="BLOCKED", offer_id=offer_id)

    if user_row["cooldown_until"] is not None and user_row["cooldown_until"] > now:
        return AcceptOfferResponse(status="COOLDOWN", offer_id=offer_id)

    # 2) oferta deve ser do restaurante do staff
    # (evita um staff de outro restaurante testando oferta alheia)
    owner = (await db.execute(
        text("SELECT 1 FROM offers WHERE id = :oid AND restaurant_id = :rid"),
        {"oid": offer_id, "rid": rid},
    )).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Offer not found for this restaurant")

    # 3) must be targeted (ajuste aqui se sua regra for released_at NOT NULL)
    target = (await db.execute(
        text("""
            SELECT 1
            FROM offer_targets
            WHERE offer_id = :oid
              AND user_id = :uid
              AND released_at IS NOT NULL
        """),
        {"oid": offer_id, "uid": user_id},
    )).first()
    if not target:
        return AcceptOfferResponse(status="OFFER_NOT_ELIGIBLE", offer_id=offer_id, user_id=user_id)

    # 4) lock offer row (FCFS)
    offer = (await db.execute(
        text("""
            SELECT id, status, end_at, accept_limit, accepted_count, accept_ttl_hours
            FROM offers
            WHERE id = :oid
            FOR UPDATE
        """),
        {"oid": offer_id},
    )).mappings().first()

    if not offer or offer["status"] != "ACTIVE" or offer["end_at"] <= now:
    # tenta pegar info mínima pra satisfazer schema
        meta = (await db.execute(
            text("""
                SELECT accept_limit, accepted_count
                FROM offers
                WHERE id = :oid
               """),
               {"oid": offer_id},
        )
    ).mappings().first()

    accept_limit = int(meta["accept_limit"]) if meta else 0
    accepted_count = int(meta["accepted_count"]) if meta else 0

    return AcceptOfferResponse(
        status="CLOSED",
        offer_id=offer_id,
        user_id=user_id,
        accepted_count=accepted_count,
        accept_limit=accept_limit,
    )


    accept_limit = int(offer["accept_limit"])
    accepted_count = int(offer["accepted_count"])

    if accepted_count >= accept_limit:
        return AcceptOfferResponse(
            status="SOLD_OUT",
            offer_id=offer_id,
            user_id=user_id,
            accepted_count=accepted_count,
            accept_limit=accept_limit,
        )

    # 5) se já existe claim, devolve
    existing = (await db.execute(
        text("""
            SELECT status, expires_at, qr_token
            FROM offer_claims
            WHERE offer_id = :oid AND user_id = :uid
        """),
        {"oid": offer_id, "uid": user_id},
    )).mappings().first()

    if existing:
        if existing["status"] == "ACCEPTED":
            return AcceptOfferResponse(
                status="ACCEPTED",
                offer_id=offer_id,
                user_id=user_id,
                expires_at=existing["expires_at"],
                qr_token=existing["qr_token"],
                accepted_count=accepted_count,
                accept_limit=accept_limit,
            )
        return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)

    # 6) cria claim
    ttl_hours = int(offer["accept_ttl_hours"] or 6)
    expires_at = min(offer["end_at"], now + timedelta(hours=ttl_hours))
    qr_token = uuid4()

    inserted = (await db.execute(
        text("""
            INSERT INTO offer_claims
                (offer_id, user_id, status, accepted_at, expires_at, qr_token)
            VALUES
                (:oid, :uid, 'ACCEPTED', :now, :exp, :qr)
            ON CONFLICT (offer_id, user_id) DO NOTHING
            RETURNING id
        """),
        {"oid": offer_id, "uid": user_id, "now": now, "exp": expires_at, "qr": str(qr_token)},
    )).first()

    if not inserted:
        existing2 = (await db.execute(
            text("""
                SELECT status, expires_at, qr_token
                FROM offer_claims
                WHERE offer_id = :oid AND user_id = :uid
            """),
            {"oid": offer_id, "uid": user_id},
        )).mappings().first()

        if existing2 and existing2["status"] == "ACCEPTED":
            return AcceptOfferResponse(
                status="ACCEPTED",
                offer_id=offer_id,
                user_id=user_id,
                expires_at=existing2["expires_at"],
                qr_token=existing2["qr_token"],
                accepted_count=accepted_count,
                accept_limit=accept_limit,
            )
        return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)

    # 7) increment counter sob lock
    await db.execute(
        text("UPDATE offers SET accepted_count = accepted_count + 1 WHERE id = :oid"),
        {"oid": offer_id},
    )

    # opcional: se bateu o limite, já marca SOLD_OUT
    await db.execute(
        text("""
            UPDATE offers
            SET status = CASE WHEN accepted_count >= accept_limit THEN 'SOLD_OUT' ELSE status END
            WHERE id = :oid
        """),
        {"oid": offer_id},
    )

    await db.commit()

    return AcceptOfferResponse(
        status="ACCEPTED",
        offer_id=offer_id,
        user_id=user_id,
        expires_at=expires_at,
        qr_token=qr_token,
        accepted_count=accepted_count + 1,
        accept_limit=accept_limit,
    )
