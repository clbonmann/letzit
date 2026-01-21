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
from app.schemas.client import RequestCodeRequest, ClientLoginRequest, ValidateCodeRequest

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
    return {"message": "Código enviado"}

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
    await db.execute(text("DELETE FROM client_first_access WHERE phone_e164 = :phone"), {"phone": phone})
    await db.commit()

    access_token = create_access_token(subject=client.id, extra_claims={"type": "client"})
    return {"access_token": access_token, "token_type": "bearer", "client_id": client.id}

@router.post("/validate-code")
async def validate_verification_code(
    payload: ValidateCodeRequest,
    db: AsyncSession = Depends(get_db_session)
):
    phone = payload.phone_e164.strip()
    
    # 1. Busca o código na tabela temporária (client_first_access)
    # Ordenamos pelo 'created_at' descrescente para pegar a tentativa mais recente
    query = text("""
        SELECT code, expires_at 
        FROM client_first_access 
        WHERE phone_e164 = :phone 
        ORDER BY created_at DESC 
        LIMIT 1
    """)
    result = await db.execute(query, {"phone": phone})
    record = result.mappings().one_or_none()

    # 2. Validações
    if not record:
        raise HTTPException(status_code=400, detail="Nenhuma solicitação de código encontrada.")
    
    saved_code = record['code']
    expires_at = record['expires_at']

    # Converte expires_at para fuso horário correto se necessário, ou garante comparação UTC
    if datetime.now(timezone.utc) > expires_at:
         await db.execute(text("UPDATE client_first_access SET status = 'EXPIRED' WHERE phone_e164 = :phone"), {"phone": phone})
         await db.commit()
         raise HTTPException(status_code=400, detail="Código expirado. Solicite um novo.")
  

    if saved_code != payload.code:
        raise HTTPException(status_code=400, detail="Código incorreto.")

    # 3. SUCESSO! O código está certo. Vamos criar o Cliente Oficial.
    
    # Aqui você insere na tabela 'clients'. Ajuste os campos conforme sua tabela real.
    insert_client = text("""
        INSERT INTO clients (phone_e164, fcm_token, created_at, geog , last_loc_at)
        VALUES (:phone, :fcm, NOW(), ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, NOW())
        RETURNING id
    """)
    
    try:
        res_insert = await db.execute(insert_client, {
            "phone": phone,
            "fcm": payload.fcm_token,
            "lat": payload.lat,
            "lon": payload.lon
        })
        new_client_id = res_insert.scalar()
        
        # 4. Limpeza (Opcional): Apagar o código usado da tabela temporária para não usar de novo
        await db.execute(text("UPDATE client_first_access SET status = 'FINISHED' WHERE phone_e164 = :phone"), {"phone": phone})
        
        await db.commit()

        # 5. Gerar o Token de Acesso (JWT)
        # Supondo que você tenha uma função create_access_token configurada
        # access_token = create_access_token(data={"sub": phone, "id": new_client_id})
        
        # Por enquanto, retornando um token fake para seu app não quebrar:
        fake_token = f"jwt_fake_{new_client_id}_{phone}"
        
        return {
            "message": "Cliente cadastrado com sucesso!",
            "access_token": fake_token,
            "client_id": new_client_id
        }

    except Exception as e:
        await db.rollback()
        print(f"Erro ao criar cliente: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao criar cadastro.")


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

