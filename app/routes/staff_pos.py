from __future__ import annotations

from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Body
from pydantic import BaseModel, UUID4, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session, AsyncSessionLocal
from app.deps_staff import get_current_staff
# Se você tiver um settings para checar ambiente de produção
from app.settings import settings 

router = APIRouter(prefix="/staff/pos", tags=["staff-pos"])

# --- ANALYTICS HELPER ---
async def log_analytics_task(offer_id: int, user_id: int, event: str):
    """Registra evento de analytics em background sem travar o request."""
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                text("INSERT INTO offer_analytics (offer_id, user_id, event_type) VALUES (:oid, :uid, :evt)"),
                {"oid": offer_id, "uid": user_id, "evt": event}
            )
            await session.commit()
        except Exception as e:
            # Em produção, use um logger real (ex: sentry)
            print(f"Analytics Error: {e}")

# --- SCHEMAS ---

class RedeemStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    CANCELLED = "CANCELLED"
    ALREADY_REDEEMED = "ALREADY_REDEEMED"
    NOT_ACCEPTED = "NOT_ACCEPTED"
    EXPIRED = "EXPIRED"
    REDEEMED = "REDEEMED"       
    NOT_REDEEMABLE = "NOT_REDEEMABLE" 

class RedeemRequest(BaseModel):
    qr_token: UUID4

class RedeemResponse(BaseModel):
    status: RedeemStatus
    offer_id: int
    claim_id: Optional[int] = None
    user_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    redeemed_at: Optional[datetime] = None
    # Dados para exibição no App do Garçom
    client_name: Optional[str] = None
    offer_title: Optional[str] = None
    price_to_charge: Optional[int] = None

# --- CORE LOGIC: POS (O Caixa/Garçom) ---

async def validate_offer_ownership(db: AsyncSession, offer_id: int, restaurant_id: int) -> bool:
    """Garante que o staff só mexa em ofertas do seu próprio restaurante."""
    exists = (await db.execute(
        text("SELECT 1 FROM offers WHERE id = :oid AND restaurant_id = :rid"),
        {"oid": offer_id, "rid": restaurant_id},
    )).scalar()
    return bool(exists)

@router.post("/{offer_id}/verify", response_model=RedeemResponse)
async def verify_qrcode(
    offer_id: int,
    payload: RedeemRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    LEITURA (Read-Only): O garçom aponta a câmera e o sistema diz se é válido.
    Não queima o cupom ainda.
    """
    rid = int(staff["restaurant_id"])
    if not await validate_offer_ownership(db, offer_id, rid):
        raise HTTPException(404, "Oferta não encontrada ou pertence a outro restaurante.")

    now = datetime.now(timezone.utc)

    # Busca dados completos (Join com User e Offer para mostrar na tela do garçom)
    query = text("""
        SELECT 
            c.id, c.offer_id, c.user_id, c.status, c.expires_at, c.redeemed_at, c.canceled_at,
            u.name as user_name,
            o.title as offer_title,
            o.price_cents
        FROM offer_claims c
        JOIN users u ON u.id = c.user_id
        JOIN offers o ON o.id = c.offer_id
        WHERE c.qr_token = :qr AND c.offer_id = :oid
    """)
    
    row = (await db.execute(query, {"qr": str(payload.qr_token), "oid": offer_id})).mappings().first()

    # Árvore de Decisão
    if not row:
        return RedeemResponse(status=RedeemStatus.INVALID, offer_id=offer_id)

    base_resp = RedeemResponse(
        status=RedeemStatus.INVALID,
        offer_id=offer_id,
        claim_id=row.id,
        user_id=row.user_id,
        client_name=row.user_name,
        offer_title=row.offer_title,
        price_to_charge=row.price_cents
    )

    if row.canceled_at:
        base_resp.status = RedeemStatus.CANCELLED
        return base_resp

    if row.redeemed_at or row.status == "REDEEMED":
        base_resp.status = RedeemStatus.ALREADY_REDEEMED
        base_resp.redeemed_at = row.redeemed_at
        return base_resp

    if row.status != "ACCEPTED":
        base_resp.status = RedeemStatus.NOT_ACCEPTED
        return base_resp

    if row.expires_at <= now:
        base_resp.status = RedeemStatus.EXPIRED
        return base_resp

    # Se passou por tudo, é válido!
    base_resp.status = RedeemStatus.VALID
    base_resp.expires_at = row.expires_at
    return base_resp


@router.post("/{offer_id}/consume", response_model=RedeemResponse)
async def consume_qrcode(
    offer_id: int,
    payload: RedeemRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    AÇÃO DE QUEIMA (Write): O garçom clica em "Confirmar/Validar".
    Efetiva o uso do cupom no banco de dados.
    """
    rid = int(staff["restaurant_id"])
    if not await validate_offer_ownership(db, offer_id, rid):
        raise HTTPException(404, "Oferta não encontrada.")

    now = datetime.now(timezone.utc)

    # 1. Lock para evitar dupla validação simultânea (Concorrência)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"redeem:{payload.qr_token}"})

    # 2. Tenta Atualizar (Happy Path)
    updated = (await db.execute(
        text("""
            UPDATE offer_claims
            SET status = 'REDEEMED', redeemed_at = :now
            WHERE qr_token = :qr
              AND offer_id = :oid
              AND canceled_at IS NULL
              AND redeemed_at IS NULL
              AND status = 'ACCEPTED'
              AND expires_at > :now
            RETURNING id, user_id, redeemed_at
        """),
        {"qr": str(payload.qr_token), "oid": offer_id, "now": now},
    )).mappings().first()

    if updated:
        # Atualiza contadores da oferta (Opcional, mas recomendado)
        await db.execute(text("UPDATE offers SET claimed_count = claimed_count + 1 WHERE id = :oid"), {"oid": offer_id})
        
        await db.commit()
        
        # Analytics
        background_tasks.add_task(log_analytics_task, offer_id, updated.user_id, "REDEEM")

        return RedeemResponse(
            status=RedeemStatus.REDEEMED,
            offer_id=offer_id,
            claim_id=updated.id,
            user_id=updated.user_id,
            redeemed_at=updated.redeemed_at
        )

    # 3. Falha (Unhappy Path)
    await db.rollback()
    
    # Chama o verify para retornar o motivo exato do erro (Expirado? Já usado?)
    return await verify_qrcode(offer_id, payload, db, staff)


# --- DEBUG TOOLS (Antigo staff_debug_accept.py) ---
# Útil para testar o sistema sem precisar do App do Cliente

class DebugAcceptRequest(BaseModel):
    user_id: int

@router.post("/{offer_id}/debug/force-accept", summary="[DEBUG] Simular Aceite de Cliente")
async def debug_force_accept_as_user(
    offer_id: int,
    payload: DebugAcceptRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    FERRAMENTA DE TESTE:
    Permite que o Staff force um usuário a "Aceitar" a oferta.
    Isso gera um QR Code válido para que você possa testar o endpoint /consume acima.
    """
    # Trava de segurança para produção (opcional)
    # if settings.ENV == "prod": raise HTTPException(403, "Debug only")

    rid = int(staff["restaurant_id"])
    uid = payload.user_id
    now = datetime.now(timezone.utc)

    # Verifica se oferta pertence ao restaurante
    if not await validate_offer_ownership(db, offer_id, rid):
        raise HTTPException(404, "Oferta não encontrada.")

    # Busca regras da oferta
    offer = (await db.execute(
        text("SELECT end_at, accept_ttl_hours FROM offers WHERE id = :oid"),
        {"oid": offer_id}
    )).mappings().first()

    if not offer:
        raise HTTPException(404, "Oferta inválida.")

    # Calcula expiração
    ttl = offer.accept_ttl_hours or 6
    expires_at = min(offer.end_at, now + timedelta(hours=ttl))
    qr_token = uuid4()

    # Insere o Claim (Aceite)
    # Usa ON CONFLICT para não quebrar se tentar duas vezes
    await db.execute(
        text("""
            INSERT INTO offer_claims (offer_id, user_id, status, accepted_at, expires_at, qr_token)
            VALUES (:oid, :uid, 'ACCEPTED', :now, :exp, :qr)
            ON CONFLICT (offer_id, user_id) 
            DO UPDATE SET status='ACCEPTED', expires_at=:exp, qr_token=:qr, redeemed_at=NULL
        """),
        {"oid": offer_id, "uid": uid, "now": now, "exp": expires_at, "qr": str(qr_token)}
    )
    
    # Incrementa contador de aceites da oferta
    await db.execute(text("UPDATE offers SET accepted_count = accepted_count + 1 WHERE id = :oid"), {"oid": offer_id})
    
    await db.commit()

    return {
        "status": "DEBUG_ACCEPTED",
        "message": f"Usuário {uid} aceitou oferta {offer_id} forçadamente.",
        "qr_token": qr_token,
        "instructions": "Use este qr_token no endpoint /verify ou /consume para testar."
    }
