from datetime import datetime, timedelta, timezone
import random
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.security import create_access_token  # Reutilizando sua função existente

router = APIRouter(prefix="/auth/users", tags=["auth-users"])

class RequestCodeRequest(BaseModel):
    phone_e164: str  # Ex: +5511999999999

class LoginRequest(BaseModel):
    phone_e164: str
    code: str

@router.post("/request-code")
async def request_code(
    payload: RequestCodeRequest,
    db: AsyncSession = Depends(get_db_session)
):
    # 1. Normaliza o telefone (remove espaços e traços se tiver)
    phone = payload.phone_e164.strip()
    
    # 2. Gera código de 6 dígitos
    # PARA PRODUÇÃO: Substitua por random.randint(100000, 999999)
    # PARA TESTE: Vamos deixar fixo ou fácil de ver
    code = str(random.randint(100000, 999999))
    
    # DICA DE DESENVOLVEDOR: Se quiser testar fácil, descomente a linha abaixo:
    # code = "111111" 

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    # 3. Salva no banco
    await db.execute(
        text("""
            INSERT INTO verification_codes (phone_e164, code, expires_at)
            VALUES (:phone, :code, :exp)
        """),
        {"phone": phone, "code": code, "exp": expires_at}
    )
    await db.commit()

    # 4. "Envia" o SMS
    # Aqui entraria a chamada para Twilio/AWS SNS.
    # Por enquanto, vamos apenas printar no log do Railway.
    print(f"=== SMS SIMULADO PARA {phone}: CÓDIGO {code} ===")

    return {"message": "Code sent (check logs for dev environment)"}


@router.post("/login")
async def login_user(
    # REMOVA: payload: LoginRequest
    # ADICIONE: form_data para aceitar o que o Swagger envia
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db_session)
):
    now = datetime.now(timezone.utc)
    
    # Mapeamento: O Swagger envia 'username', mas nós tratamos como 'telefone'
    phone = form_data.username.strip() 
    
    # Mapeamento: O Swagger envia 'password', mas nós tratamos como 'código'
    code_received = form_data.password.strip()

    # 1. Busca o código válido mais recente
    row = (await db.execute(
        text("""
            SELECT code, expires_at
            FROM verification_codes
            WHERE phone_e164 = :phone
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"phone": phone}
    )).mappings().first()

    if not row:
        raise HTTPException(status_code=400, detail="No code requested")
    
    # Compara com o código que veio no campo 'password' do form_data
    if row["code"] != code_received:
        raise HTTPException(status_code=400, detail="Invalid code")
        
    if row["expires_at"] < now:
        raise HTTPException(status_code=400, detail="Code expired")

    # 2. Código validado! Agora busca ou cria o usuário (Auto-Registration)
    user = (await db.execute(
        text("SELECT id FROM users WHERE phone_e164 = :phone"),
        {"phone": phone}
    )).mappings().first()

    user_id = None

    if user:
        user_id = user["id"]
    else:
        # Usuário novo? Cria na hora!
        new_user = (await db.execute(
            text("""
                INSERT INTO users (phone_e164, level, reputation)
                VALUES (:phone, 1, 100)
                RETURNING id
            """),
            {"phone": phone}
        )).mappings().first()
        user_id = new_user["id"]
        
        # Cria stats zerados
        await db.execute(
            text("INSERT INTO user_stats (user_id) VALUES (:uid)"),
            {"uid": user_id}
        )
        await db.commit()

    # 3. Gera o Token JWT
    access_token = create_access_token(subject=str(user_id))

    # Limpa os códigos usados
    await db.execute(
        text("DELETE FROM verification_codes WHERE phone_e164 = :phone"),
        {"phone": phone}
    )
    await db.commit()

    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "user_id": user_id,
        "is_new_user": user is None
    }
