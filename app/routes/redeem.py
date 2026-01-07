from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.schemas.redeem import RedeemVerifyRequest, RedeemVerifyResponse

router = APIRouter(prefix="/offers", tags=["redeem"])


@router.post("/{offer_id}/redeem/verify", response_model=RedeemVerifyResponse)
async def redeem_verify_qr(
    offer_id: int,
    payload: RedeemVerifyRequest,
    db: AsyncSession = Depends(get_db_session),
) -> RedeemVerifyResponse:
    """
    Validação de QR (lado restaurante):
    - trava a claim (FOR UPDATE) para evitar dupla validação
    - exige status ACCEPTED
    - exige expires_at > now
    - marca REDEEMED + redeemed_at
    """
    now = datetime.now(timezone.utc)

    async with db.begin():
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

        # QR existe, mas não pertence a essa oferta
        if int(claim["offer_id"]) != int(offer_id):
            return RedeemVerifyResponse(status="INVALID", offer_id=offer_id)

        # Já foi usado
        if claim["status"] == "REDEEMED":
            return RedeemVerifyResponse(
                status="ALREADY_REDEEMED",
                offer_id=offer_id,
                claim_id=int(claim["id"]),
                user_id=int(claim["user_id"]),
                redeemed_at=claim["redeemed_at"],
            )

        # Se não está aceito, não pode resgatar
        if claim["status"] != "ACCEPTED":
            return RedeemVerifyResponse(
                status="NOT_ACCEPTED",
                offer_id=offer_id,
                claim_id=int(claim["id"]),
                user_id=int(claim["user_id"]),
            )

        # Expirado
        if claim["expires_at"] <= now:
            # opcional: marcar NO_SHOW aqui ou deixar para um job
            return RedeemVerifyResponse(
                status="EXPIRED",
                offer_id=offer_id,
                claim_id=int(claim["id"]),
                user_id=int(claim["user_id"]),
            )

        # Marca como usado
        await db.execute(
            text("""
                UPDATE offer_claims
                SET status = 'REDEEMED',
                    redeemed_at = :now
                WHERE id = :claim_id
            """),
            {"now": now, "claim_id": int(claim["id"])},
        )

        return RedeemVerifyResponse(
            status="REDEEMED",
            offer_id=offer_id,
            claim_id=int(claim["id"]),
            user_id=int(claim["user_id"]),
            redeemed_at=now,
        )
