from __future__ import annotations

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
    """
    FCFS robusto:
    - exige que o usuário esteja liberado em offer_targets
    - trava a offer (FOR UPDATE)
    - respeita accept_limit
    - cria claim (ACCEPTED) com expires_at e qr_token
    - incrementa accepted_count apenas se inseriu claim de fato
    """

    now = datetime.now(timezone.utc)

    # 1) Checa elegibilidade básica do usuário (blocked/cooldown)
    user_row = (await db.execute(
        text("""
            SELECT is_blocked, cooldown_until
            FROM users
            WHERE id = :user_id
        """),
        {"user_id": user_id},
    )).mappings().first()

    if not user_row:
        # opcional: auto-criar user aqui; por enquanto, devolve NOT_ELIGIBLE
        return AcceptOfferResponse(status="NOT_ELIGIBLE", offer_id=offer_id)

    if user_row["is_blocked"]:
        return AcceptOfferResponse(status="BLOCKED", offer_id=offer_id)

    cooldown_until = user_row["cooldown_until"]
    if cooldown_until is not None and cooldown_until > now:
        return AcceptOfferResponse(status="COOLDOWN", offer_id=offer_id)

    # 2) Usuário precisa estar na lista liberada (offer_targets)
    target = (await db.execute(
        text("""
            SELECT 1
            FROM offer_targets
            WHERE offer_id = :offer_id AND user_id = :user_id
        """),
        {"offer_id": offer_id, "user_id": user_id},
    )).first()

    if not target:
        return AcceptOfferResponse(status="NOT_ELIGIBLE", offer_id=offer_id)

    # 3) Transação + lock na oferta (FCFS)
    async with db.begin():
        offer = (await db.execute(
            text("""
                SELECT id, status, end_at, accept_limit, accepted_count, accept_ttl_hours
                FROM offers
                WHERE id = :offer_id
                FOR UPDATE
            """),
            {"offer_id": offer_id},
        )).mappings().first()

        if not offer:
            return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)

        # status / expiração
        if offer["status"] != "ACTIVE":
            return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)

        if offer["end_at"] <= now:
            # opcional: marcar como EXPIRED
            await db.execute(
                text("UPDATE offers SET status = 'EXPIRED' WHERE id = :offer_id"),
                {"offer_id": offer_id},
            )
            return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)

        accept_limit = int(offer["accept_limit"])
        accepted_count = int(offer["accepted_count"])

        if accepted_count >= accept_limit:
            return AcceptOfferResponse(
                status="SOLD_OUT",
                offer_id=offer_id,
                accepted_count=accepted_count,
                accept_limit=accept_limit,
            )

        # 4) Se já existe claim, retorna o estado atual
        existing = (await db.execute(
            text("""
                SELECT status, expires_at, qr_token
                FROM offer_claims
                WHERE offer_id = :offer_id AND user_id = :user_id
            """),
            {"offer_id": offer_id, "user_id": user_id},
        )).mappings().first()

        if existing:
            # Se já aceitou, devolve o mesmo QR/expiração
            if existing["status"] == "ACCEPTED":
                return AcceptOfferResponse(
                    status="ACCEPTED",
                    offer_id=offer_id,
                    expires_at=existing["expires_at"],
                    qr_token=existing["qr_token"],
                    accepted_count=accepted_count,
                    accept_limit=accept_limit,
                )
            # Se já resgatou/cancelou/no_show, considera “não pode aceitar de novo”
            return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)

        # 5) Cria claim + incrementa contador (somente se inseriu)
        ttl_hours = int(offer["accept_ttl_hours"] or 6)
        expires_at = now + timedelta(hours=ttl_hours)
        qr_token = uuid4()

        # INSERT protegido por UNIQUE (offer_id, user_id)
        inserted = (await db.execute(
            text("""
                INSERT INTO offer_claims
                    (offer_id, user_id, status, accepted_at, expires_at, qr_token)
                VALUES
                    (:offer_id, :user_id, 'ACCEPTED', :accepted_at, :expires_at, :qr_token)
                ON CONFLICT (offer_id, user_id) DO NOTHING
                RETURNING id
            """),
            {
                "offer_id": offer_id,
                "user_id": user_id,
                "accepted_at": now,
                "expires_at": expires_at,
                "qr_token": str(qr_token),
            },
        )).first()

        if not inserted:
            # corrida: outro request inseriu simultaneamente
            existing2 = (await db.execute(
                text("""
                    SELECT status, expires_at, qr_token
                    FROM offer_claims
                    WHERE offer_id = :offer_id AND user_id = :user_id
                """),
                {"offer_id": offer_id, "user_id": user_id},
            )).mappings().first()

            if existing2 and existing2["status"] == "ACCEPTED":
                return AcceptOfferResponse(
                    status="ACCEPTED",
                    offer_id=offer_id,
                    expires_at=existing2["expires_at"],
                    qr_token=existing2["qr_token"],
                    accepted_count=accepted_count,
                    accept_limit=accept_limit,
                )

            return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)

        # incrementa accepted_count de forma atômica (estamos com lock FOR UPDATE)
        await db.execute(
            text("""
                UPDATE offers
                SET accepted_count = accepted_count + 1
                WHERE id = :offer_id
            """),
            {"offer_id": offer_id},
        )

        accepted_count += 1

        return AcceptOfferResponse(
            status="ACCEPTED",
            offer_id=offer_id,
            expires_at=expires_at,
            qr_token=qr_token,
            accepted_count=accepted_count,
            accept_limit=accept_limit,
        )
