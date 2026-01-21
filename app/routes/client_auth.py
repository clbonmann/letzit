from datetime import datetime, timedelta, timezone
import random
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
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
    """
    Gera código SMS simulado APENAS se o cliente NÃO existir.
    """
    phone = payload.phone_e164.strip()

    # 1. VERIFICAÇÃO: Checa se o telefone já existe na tabela 'clients'
    # Ajuste o nome da coluna 'phone' abaixo caso no seu banco seja 'phone_e164'
    query_check = text("SELECT 1 FROM clients WHERE phone_e164 = :phone LIMIT 1")
    result = await db.execute(query_check, {"phone": phone})
    client_exists = result.scalar()

    if client_exists:
        # Retorna erro 400 (Bad Request) e para a execução aqui
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este número de telefone já possui cadastro."
        )

    # --- Se passou daqui, é porque o telefone NÃO existe ---

    code = str(random.randint(100000, 999999))  # Código aleatório de 6 dígitos
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    # 2. Insere na tabela de primeiro acesso
    await db.execute(
        text("INSERT INTO client_first_access (phone_e164, code, expires_at, created_at) VALUES (:phone, :code, :exp, NOW())"),
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
    phone = form_data.clientname.strip()
    code_received = form_data.password.strip()
    now = datetime.now(timezone.utc)

    row = (await db.execute(
        text("SELECT code, expires_at FROM client_first_access WHERE phone_e164 = :phone ORDER BY created_at DESC LIMIT 1"),
        {"phone": phone}
    )).mappings().first()

    if not row or row["code"] != code_received or row["expires_at"] < now:
        raise HTTPException(400, "Código inválido ou expirado.")

    query = text("""
        INSERT INTO public.clients (phone_e164, created_at, "level", reputation, is_blocked, last_loc_at, geog) 
        VALUES (:phone, NOW(), 1, 5.0, FALSE, NOW(), ST_SetSRID(ST_MakePoint(0, 0), 4326))
        ON CONFLICT (phone_e164) DO UPDATE SET last_loc_at = NOW()
        RETURNING id, is_blocked
    """)
    client = (await db.execute(query, {"phone": phone})).mappings().first()
    await db.commit()

    if client.is_blocked: raise HTTPException(403, "Conta bloqueada.")
    await db.execute(text("DELETE FROM verification_codes WHERE phone_e164 = :phone"), {"phone": phone})
    await db.commit()

    access_token = create_access_token(subject=client.id, extra_claims={"type": "client"})
    return {"access_token": access_token, "token_type": "bearer", "client_id": client.id}

@router.post("/login")
async def client_login_app(
    payload: ClientLoginRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """[OFICIAL] Login via App."""
    query = text("""
        INSERT INTO public.clients (phone_e164, created_at, "level", reputation, is_blocked, geog, last_loc_at, loc_accuracy_m, fcm_token) 
        VALUES (:phone, NOW(), 1, 5.0, FALSE, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), NOW(), :acc, :fcm)
        ON CONFLICT (phone_e164) DO UPDATE SET last_loc_at = NOW(), geog = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), loc_accuracy_m = :acc, fcm_token = COALESCE(:fcm, clients.fcm_token)
        RETURNING id, is_blocked, reputation, "level"
    """)
    
    try:
        client = (await db.execute(query, {
            "phone": payload.phone, "lat": payload.lat, "lon": payload.lon, "acc": payload.accuracy, "fcm": payload.fcm_token
        })).mappings().first()
        await db.commit()
    except Exception as e:
        await db.rollback()
        print(f"Erro login: {e}")
        raise HTTPException(500, "Erro ao processar login.")

    if client.is_blocked: raise HTTPException(403, "Conta bloqueada.")

    access_token = create_access_token(subject=client.id, extra_claims={"type": "client", "lvl": client.level})
    return {"access_token": access_token, "token_type": "bearer", "client_id": client.id, "reputation": client.reputation}

