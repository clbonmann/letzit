from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db import get_db_session

router = APIRouter(prefix="/offers", tags=["offers"])


@router.post("/{offer_id}/accept")
async def accept_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db_session),
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
):
    if not x_user_id:
        raise HTTPException(401, "X-User-Id header required")

    uid = int(x_user_id)
    oid = int(offer_id)
    now = datetime.now(timezone.utc)

    # FCFS: lock por oferta
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": oid})

    try:
        # 1) oferta válida?
        o = (await db.execute(
            text("""
                SELECT id, accept_limit, accepted_count, status, end_at
                FROM offers
                WHERE id = :oid
            """),
            {"oid": oid},
        )).mappings().first()

        if not o:
            raise HTTPException(404, "Offer not found")

        if o["status"] != "ACTIVE":
            raise HTTPException(409, "Offer not ACTIVE")

        if o["end_at"] <= now:
            raise HTTPException(409, "Offer expired")

        # 2) idempotência: já aceitou?
        existing = (await db.execute(
            text("""
                SELECT id, status, qr_token, expires_at
                FROM offer_claims
                WHERE offer_id = :oid AND user_id = :uid
            """),
            {"oid": oid, "uid": uid},
        )).mappings().first()

        if existing:
            return {
                "status": "ALREADY_ACCEPTED",
                "offer_id": oid,
                "user_id": uid,
                "claim_status": existing["status"],
                "qr_token": str(existing["qr_token"]),
                "expires_at": existing["expires_at"],
                "qr_payload": f"LETZIT:{existing['qr_token']}",
            }

        # 3) limite FCFS
        if int(o["accepted_count"]) >= int(o["accept_limit"]):
            raise HTTPException(409, "SOLD_OUT")

        # 4) gera QR token (UUID) e expiração do cupom (6h, mas nunca além do end_at)
        qr_token = uuid4()
        expires_at = min(o["end_at"], now + timedelta(hours=6))

        # 5) cria claim
        await db.execute(
            text("""
                INSERT INTO offer_claims (
                    offer_id, user_id, status, accepted_at, expires_at, qr_token
                )
                VALUES (
                    :oid, :uid, 'ACCEPTED', :now, :expires_at, :qr_token
                )
            """),
            {
                "oid": oid,
                "uid": uid,
                "now": now,
                "expires_at": expires_at,
                "qr_token": qr_token,
            },
        )

        # 6) incrementa contador com guarda (garante não estourar)
        updated = (await db.execute(
            text("""
                UPDATE offers
                SET accepted_count = accepted_count + 1
                WHERE id = :oid
                  AND accepted_count < accept_limit
                  AND status = 'ACTIVE'
                  AND end_at > now()
                RETURNING accepted_count
            """),
            {"oid": oid},
        )).scalar_one_or_none()

        if updated is None:
            await db.rollback()
            raise HTTPException(409, "SOLD_OUT")

        await db.commit()

        return {
            "status": "ACCEPTED",
            "offer_id": oid,
            "user_id": uid,
            "qr_token": str(qr_token),
            "expires_at": expires_at,
            "qr_payload": f"LETZIT:{qr_token}",
        }

    except IntegrityError:
        await db.rollback()
        # unique (offer_id,user_id) ou qr_token
        raise HTTPException(409, "Conflict (try again)")
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
