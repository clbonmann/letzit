from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps import get_current_user_id
from app.schemas.offers import AcceptOfferResponse

router = APIRouter(prefix="/offers", tags=["offers"])

@router.post("/{offer_id}/accept", response_model=AcceptOfferResponse)
async def accept_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db_session),
    user_id: int = Depends(get_current_user_id),
) -> AcceptOfferResponse:
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

    # 2) must be targeted
    target = (
        await db.execute(
            text("""
             SELECT 1
             FROM offer_targets
             WHERE offer_id = :oid
             AND user_id = :uid
             AND released_at IS NOT NULL
             """),
            {"oid": offer_id, "uid": user_id},
        )
    ).first()
    if not target:
        return AcceptOfferResponse(status="OFFER_NOT_ELIGIBLE", offer_id=offer_id, user_id=user_id)

    # 3) lock offer row (this is the FCFS part)
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
        return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)

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

    # 4) if already claimed, return it
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

    # 5) insert claim
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
        # someone inserted concurrently
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

    # 6) increment counter (still under the offer lock)
    await db.execute(
        text("UPDATE offers SET accepted_count = accepted_count + 1 WHERE id = :oid"),
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
