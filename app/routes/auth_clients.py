from datetime import datetime, timedelta, timezone
import random
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.security import create_access_token
# Se você tiver schemas separados, pode importar. 
# Se não, mantenha as classes abaixo para garantir que tudo funcione num arquivo só.

router = APIRouter(prefix="/client/auth", tags=["client-auth"])

# --- SCHEMAS (Modelos de Dados) ---

class RequestCodeRequest(BaseModel):
    phone_e164: str  # Ex: +5511999999999

class ClientLoginRequest(BaseModel):
    phone: str          # Formato E.164: +5511999998888
    
    # Geo (Obrigatório para o App funcionar e calcular ofertas)
    lat: float
    lon: float
    accuracy: Optional[float] = 0.0
    
    # Token de Push (Obrigatório para o Smart Batch enviar notificações)
    fcm_token: Optional[str] = None 

# --- ENDPOINTS ---

@router.post("/request-code")
async def request_verification_code(
    payload: RequestCodeRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """
    [BACKUP/TESTE] Gera um código de 6 dígitos para SMS manual.
    Use isso no Postman/Swagger se não quiser usar o Firebase no frontend ainda.
    """
    phone = payload.phone_e164.strip()
    
    # 1. Gera código (Fixo 111111 para facilitar testes)
    code = "111111" 
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    # 2. Salva na tabela auxiliar
    await db.execute(
        text("""
            INSERT INTO verification_codes (phone_e164, code, expires_at)
            VALUES (:phone, :code, :exp)
        """),
        {"phone": phone, "code": code, "exp": expires_at}
    )
    await db.commit()

    print(f"=== SMS SIMULADO PARA {phone}: CÓDIGO {code} ===")
    return {"message": "Código enviado (olhe os logs do servidor)"}


@router.post("/login/manual")
async def login_manual(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db_session)
):
    """
    [BACKUP/TESTE] Valida o código gerado no /request-code e loga.
    Isso permite testar a API e pegar um Token válido sem usar o App real.
    - Username: Telefone
    - Password: O código (111111)
    """
    phone = form_data.username.strip()
    code_received = form_data.password.strip()
    now = datetime.now(timezone.utc)

    # 1. Valida o código na tabela auxiliar
    row = (await db.execute(
        text("""
            SELECT code, expires_at FROM verification_codes
            WHERE phone_e164 = :phone
            ORDER BY created_at DESC LIMIT 1
        """),
        {"phone": phone}
    )).mappings().first()

    if not row:
        raise HTTPException(400, "Nenhum código solicitado para este número.")
    if row["code"] != code_received:
        raise HTTPException(400, "Código inválido.")
    if row["expires_at"] < now:
        raise HTTPException(400, "Código expirado.")

    # 2. Busca ou Cria o Usuário (UPSERT simplificado para teste manual)
    query = text("""
        INSERT INTO public.users (
            phone_e164, created_at, "level", reputation, is_blocked,
            last_loc_at, geog
        ) VALUES (
            :phone, NOW(), 1, 5.0, FALSE,
            NOW(), ST_SetSRID(ST_MakePoint(0, 0), 4326)
        )
        ON CONFLICT (phone_e164) DO UPDATE SET
            last_loc_at = NOW()
        RETURNING id, is_blocked
    """)
    
    user = (await db.execute(query, {"phone": phone})).mappings().first()
    await db.commit()

    if user.is_blocked:
        raise HTTPException(403, "Conta bloqueada.")

    # 3. Limpa códigos usados
    await db.execute(text("DELETE FROM verification_codes WHERE phone_e164 = :phone"), {"phone": phone})
    await db.commit()

    # 4. Gera Token JWT
    access_token = create_access_token(
        subject=user.id, 
        extra_claims={"type": "client"}
    )
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.id}


@router.post("/login")
async def client_login_app(
    payload: ClientLoginRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """
    [OFICIAL] Login via App (Firebase/Google/Apple).
    O Frontend manda o telefone verificado + localização + FCM Token.
    """
    
    query = text("""
        INSERT INTO public.users (
            phone_e164, 
            created_at, 
            "level", 
            reputation, 
            is_blocked,
            geog, 
            last_loc_at, 
            loc_accuracy_m,
            fcm_token
        ) VALUES (
            :phone, 
            NOW(), 
            1,   -- Level inicial
            5.0, -- Reputação inicial
            FALSE,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
            NOW(),
            :acc,
            :fcm
        )
        ON CONFLICT (phone_e164) DO UPDATE SET
            last_loc_at = NOW(),
            geog = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
            loc_accuracy_m = :acc,
            fcm_token = COALESCE(:fcm, users.fcm_token)
        RETURNING id, is_blocked, reputation, "level"
    """)
    
    try:
        result = await db.execute(query, {
            "phone": payload.phone,
            "lat": payload.lat,
            "lon": payload.lon,
            "acc": payload.accuracy,
            "fcm": payload.fcm_token
        })
        user = result.mappings().first()
        await db.commit()
    except Exception as e:
        await db.rollback()
        print(f"Erro no login: {e}")
        raise HTTPException(500, "Erro ao processar login.")

    if user.is_blocked:
        raise HTTPException(403, "Sua conta está bloqueada.")

    # Token JWT do Cliente
    access_token = create_access_token(
        subject=user.id,
        extra_claims={
            "type": "client", 
            "lvl": user.level 
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "reputation": user.reputation
    }
