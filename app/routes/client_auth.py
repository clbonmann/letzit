from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.security import create_access_token
# IMPORTANDO O SCHEMA
from app.schemas.client import RequestCodeRequest, ClientLoginRequest

router = APIRouter(prefix="/client/auth", tags=["client-auth"])

@router.post("/request-code")
async def request_verification_code(
    payload: RequestCodeRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """[BACKUP/TESTE] Gera código SMS simulado."""
    phone = payload.phone_e164.strip()
    code = "111111" 
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    await db.execute(
        text("INSERT INTO verification_codes (phone_e164, code, expires_at) VALUES (:phone, :code, :exp)"),
        {"phone": phone, "code": code, "exp": expires_at}
    )
    await db.commit()
    print(f"=== SMS SIMULADO PARA {phone}: CÓDIGO {code} ===")
    return {"message": "Código enviado (olhe os logs)"}

@router.post("/login/manual")
async def login_manual(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db_session)
):
    """[BACKUP/TESTE] Login manual via código."""
    phone = form_data.username.strip()
    code_received = form_data.password.strip()
    now = datetime.now(timezone.utc)

    row = (await db.execute(
        text("SELECT code, expires_at FROM verification_codes WHERE phone_e164 = :phone ORDER BY created_at DESC LIMIT 1"),
        {"phone": phone}
    )).mappings().first()

    if not row or row["code"] != code_received or row["expires_at"] < now:
        raise HTTPException(400, "Código inválido ou expirado.")

    query = text("""
        INSERT INTO public.users (phone_e164, created_at, "level", reputation, is_blocked, last_loc_at, geog) 
        VALUES (:phone, NOW(), 1, 5.0, FALSE, NOW(), ST_SetSRID(ST_MakePoint(0, 0), 4326))
        ON CONFLICT (phone_e164) DO UPDATE SET last_loc_at = NOW()
        RETURNING id, is_blocked
    """)
    user = (await db.execute(query, {"phone": phone})).mappings().first()
    await db.commit()

    if user.is_blocked: raise HTTPException(403, "Conta bloqueada.")
    await db.execute(text("DELETE FROM verification_codes WHERE phone_e164 = :phone"), {"phone": phone})
    await db.commit()

    access_token = create_access_token(subject=user.id, extra_claims={"type": "client"})
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.id}

@router.post("/login")
async def client_login_app(
    payload: ClientLoginRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """[OFICIAL] Login via App."""
    query = text("""
        INSERT INTO public.users (phone_e164, created_at, "level", reputation, is_blocked, geog, last_loc_at, loc_accuracy_m, fcm_token) 
        VALUES (:phone, NOW(), 1, 5.0, FALSE, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), NOW(), :acc, :fcm)
        ON CONFLICT (phone_e164) DO UPDATE SET last_loc_at = NOW(), geog = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), loc_accuracy_m = :acc, fcm_token = COALESCE(:fcm, users.fcm_token)
        RETURNING id, is_blocked, reputation, "level"
    """)
    
    try:
        user = (await db.execute(query, {
            "phone": payload.phone, "lat": payload.lat, "lon": payload.lon, "acc": payload.accuracy, "fcm": payload.fcm_token
        })).mappings().first()
        await db.commit()
    except Exception as e:
        await db.rollback()
        print(f"Erro login: {e}")
        raise HTTPException(500, "Erro ao processar login.")

    if user.is_blocked: raise HTTPException(403, "Conta bloqueada.")

    access_token = create_access_token(subject=user.id, extra_claims={"type": "client", "lvl": user.level})
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.id, "reputation": user.reputation}

