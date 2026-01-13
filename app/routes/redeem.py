from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel, UUID4
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session, AsyncSessionLocal # Precisamos da Factory para o Analytics
from app.deps_staff import get_current_staff

# Se você já tiver essa função de analytics em outro arquivo, importe-a.
# Caso contrário, defina aqui ou num utils.
async def log_analytics_task(offer_id: int, user_id: int, event: str):
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                text("INSERT INTO offer_analytics (offer_id, user_id, event_type) VALUES (:oid, :uid, :evt)"),
                {"oid": offer_id, "uid": user_id, "evt": event}
            )
            await session.commit()
        except Exception as e:
            print(f"Analytics Error: {e}")

router = APIRouter(prefix="/offers", tags=["redeem"])

# --- SCHEMAS (Definidos aqui para clareza, mova para app/schemas se preferir) ---

class RedeemStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    CANCELLED = "CANCELLED"
    ALREADY_REDEEMED = "ALREADY_REDEEMED"
    NOT_ACCEPTED = "NOT_ACCEPTED"
    EXPIRED = "EXPIRED"
    REDEEMED = "REDEEMED"       # Sucesso
    NOT_REDEEMABLE = "NOT_REDEEMABLE" # Erro genérico

class RedeemVerifyRequest(BaseModel):
    qr_token: UUID4

class RedeemResponse(BaseModel):
    status: RedeemStatus
    offer_id: int
    claim_id: Optional[int] = None
    user_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    redeemed_at: Optional[datetime] = None

# --- HELPER: Validação de Propriedade (DRY) ---
async def validate_offer_ownership(db: AsyncSession, offer_id: int, restaurant_id: int) -> bool:
    """Verifica se a oferta pertence ao restaurante do staff logado."""
    exists = (await db.execute(
        text("SELECT 1 FROM offers WHERE id = :oid AND restaurant_id = :rid"),
        {"oid": offer_id, "rid": restaurant_id},
    )).scalar()
    return bool(exists)

# --- ENDPOINT 1: VERIFICAR (Apenas leitura) ---
@router.post("/{offer_id}/redeem/verify", response_model=RedeemResponse)
async def redeem_verify_qr(
    offer_id: int,
    payload: RedeemVerifyRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> RedeemResponse:
    now = datetime.now(timezone.utc)

    # 1. Validação de Propriedade
    if not await validate_offer_ownership(db, offer_id, int(staff["restaurant_id"])):
        return RedeemResponse(status=RedeemStatus.INVALID, offer_id=offer_id)

    # 2. Busca dados cruciais
    claim = (await db.execute(
        text("""
            SELECT id, offer_id, user_id, status, expires_at, redeemed_at, canceled_at
            FROM offer_claims
            WHERE qr_token = :qr_token AND offer_id = :oid
        """),
        {"qr_token": str(payload.qr_token), "oid": offer_id},
    )).mappings().first()

    # 3. Árvore de Decisão
    if not claim:
        return RedeemResponse(status=RedeemStatus.INVALID, offer_id=offer_id)

    if claim["canceled_at"]:
        return RedeemResponse(
            status=RedeemStatus.CANCELLED,
            offer_id=offer_id, claim_id=claim.id, user_id=claim.user_id
        )

    if claim["redeemed_at"] or claim["status"] == "REDEEMED":
        return RedeemResponse(
            status=RedeemStatus.ALREADY_REDEEMED,
            offer_id=offer_id, claim_id=claim.id, user_id=claim.user_id,
            redeemed_at=claim.redeemed_at
        )

    if claim["status"] != "ACCEPTED":
        return RedeemResponse(
            status=RedeemStatus.NOT_ACCEPTED,
            offer_id=offer_id, claim_id=claim.id, user_id=claim.user_id
        )

    if claim["expires_at"] <= now:
        return RedeemResponse(
            status=RedeemStatus.EXPIRED,
            offer_id=offer_id, claim_id=claim.id, user_id=claim.user_id
        )

    # Sucesso na validação
    return RedeemResponse(
        status=RedeemStatus.VALID,
        offer_id=offer_id,
        claim_id=claim.id,
        user_id=claim.user_id,
        expires_at=claim.expires_at,
    )


# --- ENDPOINT 2: CONSUMIR (Escrita/Queima) ---
@router.post("/{offer_id}/redeem/consume", response_model=RedeemResponse)
async def redeem_consume_qr(
    offer_id: int,
    payload: RedeemVerifyRequest,
    background_tasks: BackgroundTasks, # <--- Analytics Injetado
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> RedeemResponse:
    now = datetime.now(timezone.utc)

    # 1. Validação de Propriedade
    if not await validate_offer_ownership(db, offer_id, int(staff["restaurant_id"])):
        return RedeemResponse(status=RedeemStatus.INVALID, offer_id=offer_id)

    # 2. Advisory Lock: Evita que dois caixas bipem o mesmo QR no mesmo milissegundo
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"redeem:{payload.qr_token}"},
    )

    # 3. Tentativa de Consumo Atômico (Happy Path)
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

    # 4. SUCESSO!
    if updated:
        await db.commit()
        
        # Registra Analytics em Background
        background_tasks.add_task(log_analytics_task, offer_id, updated.user_id, "USE")

        return RedeemResponse(
            status=RedeemStatus.REDEEMED,
            offer_id=offer_id,
            claim_id=updated.id,
            user_id=updated.user_id,
            redeemed_at=updated.redeemed_at,
        )

    # 5. FALHA (Unhappy Path): Descobre o motivo
    # Se o update não retornou linha, algo estava errado. Rolamos o banco e checamos o motivo.
    await db.rollback() # Libera o lock e limpa a sessão

    # Reutilizamos a lógica de verificação para saber EXATAMENTE o erro
    # Isso é muito melhor para a UX do garçom do que apenas "Erro Genérico"
    check_response = await redeem_verify_qr(offer_id, payload, db, staff)
    
    # Se o verify disser que está VALID, mas o update falhou, é um caso muito raro (race condition extrema)
    if check_response.status == RedeemStatus.VALID:
        return RedeemResponse(status=RedeemStatus.NOT_REDEEMABLE, offer_id=offer_id)
    
    return check_response
