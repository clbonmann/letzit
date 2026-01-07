from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.schemas.redeem import RedeemVerifyRequest, RedeemVerifyResponse
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/offers", tags=["redeem"])


@router.post("/{offer_id}/redeem/verify", response_model=RedeemVerifyResponse)
async def redeem_verify_qr(
    offer_id: int,
    payload: RedeemVerifyRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> RedeemVerifyResponse:

    now = datetime.now(timezone.utc)
    offer_owner = (await db.execute(
        text("""
            SELECT o.id
            FROM offers o
            WHERE o.id = :oid AND o.restaurant_id = :rid
        """),
        {"oid": offer_id, "rid": int(staff["restaurant_id"])},
    )).first()

if not offer_owner:
    return RedeemVerifyResponse(status="INVALID", offer_id=offer_id)

    # 🔒 FOR UPDATE já abre transação implicitamente
    claim = (await db.execute(
        text("""
            SELECT id, offer_id, user_id, status, expires_at, redeemed_at
            FROM offer_claims
            WHERE qr_token = :qr_token
            FOR UPDATE
        """),
        {"qr_token": str(payload.qr_token)},
    )).mappings().first()

    if not claim:
        return RedeemVerifyResponse(status="INVALID", offer_id=offer_id)

    if int(claim["offer_id"]) != int(offer_id):
        return RedeemVerifyResponse(status="INVALID", offer_id=offer_id)

    if claim["status"] == "REDEEMED":
        return RedeemVerifyResponse(
            status="ALREADY_REDEEMED",
            offer_id=offer_id,
            claim_id=int(claim["id"]),
            user_id=int(claim["user_id"]),
            redeemed_at=claim["redeemed_at"],
        )

    if claim["status"] != "ACCEPTED":
        return RedeemVerifyResponse(
            status="NOT_ACCEPTED",
            offer_id=offer_id,
            claim_id=int(claim["id"]),
            user_id=int(claim["user_id"]),
        )

    if claim["expires_at"] <= now:
        return RedeemVerifyResponse(
            status="EXPIRED",
            offer_id=offer_id,
            claim_id=int(claim["id"]),
            user_id=int(claim["user_id"]),
        )

    # ✅ Atualiza status
    await db.execute(
        text("""
            UPDATE offer_claims
            SET status = 'REDEEMED',
                redeemed_at = :now
            WHERE id = :claim_id
        """),
        {"now": now, "claim_id": int(claim["id"])},
    )

    # ✅ Commit explícito (boa prática)
    await db.commit()

    return RedeemVerifyResponse(
        status="REDEEMED",
        offer_id=offer_id,
        claim_id=int(claim["id"]),
        user_id=int(claim["user_id"]),
        redeemed_at=now,
    )
