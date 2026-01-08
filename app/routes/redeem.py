from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.schemas.redeem import (
    RedeemVerifyRequest,
    RedeemVerifyResponse,
    RedeemConsumeResponse,   # <-- crie esse schema ou ajuste
)
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

    # 1) Confere se a oferta pertence ao restaurante do staff
    offer_owner = (await db.execute(
        text("""
            SELECT id
            FROM offers
            WHERE id = :oid AND restaurant_id = :rid
        """),
        {"oid": offer_id, "rid": int(staff["restaurant_id"])},
    )).first()

    if not offer_owner:
        return RedeemVerifyResponse(status="INVALID", offer_id=offer_id)

    # 2) Busca claim do QR E garante que é da mesma offer_id
    claim = (await db.execute(
        text("""
            SELECT id, offer_id, user_id, status, expires_at, redeemed_at, canceled_at
            FROM offer_claims
            WHERE qr_token = :qr_token
              AND offer_id = :oid
        """),
        {"qr_token": str(payload.qr_token), "oid": offer_id},
    )).mappings().first()

    if not claim:
        return RedeemVerifyResponse(status="INVALID", offer_id=offer_id)

    if claim["canceled_at"] is not None:
        return RedeemVerifyResponse(
            status="CANCELLED",
            offer_id=offer_id,
            claim_id=int(claim["id"]),
            user_id=int(claim["user_id"]),
        )

    if claim["redeemed_at"] is not None or claim["status"] == "REDEEMED":
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

    # ✅ Só valida, não consome
    return RedeemVerifyResponse(
    status="VALID",
    offer_id=offer_id,
    claim_id=int(claim["id"]),
    user_id=int(claim["user_id"]),
    expires_at=claim["expires_at"],
)



@router.post("/{offer_id}/redeem/consume", response_model=RedeemConsumeResponse)
async def redeem_consume_qr(
    offer_id: int,
    payload: RedeemVerifyRequest,  # pode reutilizar (tem qr_token)
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> RedeemConsumeResponse:
    now = datetime.now(timezone.utc)

    # Confere se offer pertence ao restaurante do staff
    offer_owner = (await db.execute(
        text("""
            SELECT id
            FROM offers
            WHERE id = :oid AND restaurant_id = :rid
        """),
        {"oid": offer_id, "rid": int(staff["restaurant_id"])},
    )).first()

    if not offer_owner:
        return RedeemConsumeResponse(status="INVALID", offer_id=offer_id)

    # Lock por token (evita duplo consumo em caixas diferentes)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"redeem:{payload.qr_token}"},
    )

    # UPDATE atômico: só consome se estiver tudo certo
    updated = (await db.execute(
        text("""
            UPDATE offer_claims
            SET status = 'REDEEMED',
                redeemed_at = :now
            WHERE qr_token = :qr_token
              AND offer_id = :oid
              AND canceled_at IS NULL
              AND redeemed_at IS NULL
              AND status = 'ACCEPTED'
              AND expires_at > :now
            RETURNING id, user_id, redeemed_at
        """),
        {"qr_token": str(payload.qr_token), "oid": offer_id, "now": now},
    )).mappings().first()

    if not updated:
        await db.rollback()
        # re-usa verify para dizer o motivo (ou devolve genérico)
        return RedeemConsumeResponse(status="NOT_REDEEMABLE", offer_id=offer_id)

    await db.commit()

    return RedeemConsumeResponse(
        status="REDEEMED",
        offer_id=offer_id,
        claim_id=int(updated["id"]),
        user_id=int(updated["user_id"]),
        redeemed_at=updated["redeemed_at"],
    )
