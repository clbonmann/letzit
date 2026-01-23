from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session, AsyncSessionLocal
from app.deps_staff import get_current_staff
# IMPORTANDO SCHEMAS
from app.schemas.staff import RedeemRequest, RedeemResponse, RedeemStatus, DebugAcceptRequest, NoShowRequest

router = APIRouter(prefix="/staff/pos", tags=["staff-pos"])

async def log_analytics_task(offer_id: int, client_id: int, event: str):
    async with AsyncSessionLocal() as s:
        try:
            await s.execute(text("INSERT INTO offer_analytics (offer_id, client_id, event_type) VALUES (:oid, :uid, :evt)"), {"oid": offer_id, "uid": client_id, "evt": event})
            await s.commit()
        except Exception: pass

async def validate_owner(db, oid, rid):
    return (await db.execute(text("SELECT 1 FROM offers WHERE id=:oid AND restaurant_id=:rid"), {"oid": oid, "rid": rid})).scalar()

@router.post("/{offer_id}/verify", response_model=RedeemResponse)
async def verify_qrcode(offer_id: int, payload: RedeemRequest, db: AsyncSession = Depends(get_db_session), staff: dict = Depends(get_current_staff)):
    if not await validate_owner(db, offer_id, int(staff["restaurant_id"])): raise HTTPException(404, "Oferta inválida.")
    row = (await db.execute(text("SELECT c.*, u.name as client_name, o.title as offer_title, o.price_cents FROM offer_claims c JOIN clients u ON u.id=c.client_id JOIN offers o ON o.id=c.offer_id WHERE c.qr_token=:qr AND c.offer_id=:oid"), {"qr": str(payload.qr_token), "oid": offer_id})).mappings().first()
    
    if not row: return RedeemResponse(status=RedeemStatus.INVALID, offer_id=offer_id)
    base = RedeemResponse(status=RedeemStatus.INVALID, offer_id=offer_id, claim_id=row.id, client_id=row.client_id, client_name=row.client_name, offer_title=row.offer_title, price_to_charge=row.price_cents)
    
    if row.canceled_at: base.status = RedeemStatus.CANCELLED; return base
    if row.redeemed_at: base.status = RedeemStatus.ALREADY_REDEEMED; base.redeemed_at = row.redeemed_at; return base
    if row.status != "ACCEPTED": base.status = RedeemStatus.NOT_ACCEPTED; return base
    if row.expires_at <= datetime.now(timezone.utc): base.status = RedeemStatus.EXPIRED; return base
    
    base.status = RedeemStatus.VALID; base.expires_at = row.expires_at
    return base

@router.post("/{offer_id}/consume", response_model=RedeemResponse)
async def consume_qrcode(offer_id: int, payload: RedeemRequest, bg: BackgroundTasks, db: AsyncSession = Depends(get_db_session), staff: dict = Depends(get_current_staff)):
    if not await validate_owner(db, offer_id, int(staff["restaurant_id"])): raise HTTPException(404, "Oferta inválida.")
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"redeem:{payload.qr_token}"})
    
    upd = (await db.execute(text("UPDATE offer_claims SET status='REDEEMED', redeemed_at=NOW() WHERE qr_token=:qr AND offer_id=:oid AND status='ACCEPTED' AND expires_at>NOW() RETURNING id, client_id, redeemed_at"), {"qr": str(payload.qr_token), "oid": offer_id})).mappings().first()
    
    if upd:
        await db.execute(text("UPDATE offers SET claimed_count=claimed_count+1 WHERE id=:oid"), {"oid": offer_id})
        await db.commit()
        bg.add_task(log_analytics_task, offer_id, upd.client_id, "REDEEM")
        return RedeemResponse(status=RedeemStatus.REDEEMED, offer_id=offer_id, claim_id=upd.id, client_id=upd.client_id, redeemed_at=upd.redeemed_at)
    
    await db.execute(text("UPDATE offer_targets SET redeemed_at = NOW() WHERE client_id = :uid AND offer_id = :oid AND redeemed_at IS NULL"),{"uid": upd.client_id, "oid": offer_id})
    await db.rollback()
    return await verify_qrcode(offer_id, payload, db, staff)

@router.post("/{offer_id}/debug/force-accept")
async def debug_accept(offer_id: int, payload: DebugAcceptRequest, db: AsyncSession = Depends(get_db_session), staff: dict = Depends(get_current_staff)):
    # ... [Mesma lógica de antes] ...
    return {"status": "DEBUG_ACCEPTED"}

@router.post("/no-show")
async def mark_no_show(payload: NoShowRequest, db: AsyncSession = Depends(get_db_session), staff: dict = Depends(get_current_staff)):
    val, field = (payload.qr_token, "qr_token") if payload.qr_token else (payload.claim_id, "id")
    row = (await db.execute(text(f"SELECT c.id, c.status, c.client_id, o.restaurant_id FROM offer_claims c JOIN offers o ON o.id=c.offer_id WHERE c.{field}=:val"), {"val": val})).mappings().first()
    
    if not row or row.restaurant_id != int(staff["restaurant_id"]): raise HTTPException(404, "Reserva inválida.")
    if row.status != 'ACCEPTED': raise HTTPException(400, "Status inválido.")
    
    await db.execute(text("UPDATE offer_claims SET status='NO_SHOW', updated_at=NOW(), penalty_applied_at=NOW() WHERE id=:id"), {"id": row.id})
    await db.execute(text("UPDATE clients SET cooldown_until=GREATEST(COALESCE(cooldown_until, NOW()), NOW()+interval '24 hours') WHERE id=:uid"), {"uid": row.client_id})
    await db.commit()
    return {"message": "No-Show marcado."}

