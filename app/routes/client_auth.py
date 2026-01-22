from datetime import datetime, timedelta, timezone
import random
from typing import Optional
from geopy.geocoders import Nominatim

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext

from app.db import get_db_session
from app.security import create_access_token, get_password_hash
# IMPORTANDO O SCHEMA
from app.schemas.client import CheckPhoneRequest, CompleteRegistrationRequest, RequestCodeRequest, ClientLoginRequest, ValidateCodeRequest, get_address_from_coords

router = APIRouter(prefix="/client/auth", tags=["client-auth"])

@router.post("/check-phone")
async def check_phone(
    payload: CheckPhoneRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """Passo 1: Verifica se o telefone já existe no banco."""
    # Limpa caracteres não numéricos se necessário
    phone_clean = "".join(filter(str.isdigit, payload.phone))
    
    query = text("SELECT id FROM clients WHERE phone_e164 = :phone")
    result = await db.execute(query, {"phone": phone_clean})
    exists = result.scalar() is not None
    
    return {"exists": exists}

@router.post("/request-code")
async def request_verification_code(
    payload: RequestCodeRequest,
    db: AsyncSession = Depends(get_db_session)
):
    phone = payload.phone.strip()

    # 1. Gera o código e a expiração
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

@router.post("/validate-code")
async def validate_verification_code(
    payload: ValidateCodeRequest,
    db: AsyncSession = Depends(get_db_session)
):
    phone = payload.phone.strip()
    
    # 1. Busca o código mais recente para esse telefone
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

    return {"valid": True, "message": "Código validado com sucesso."}

@router.post("/register")
async def register_client(
    payload: CompleteRegistrationRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """Passo Final: Cria o usuário no banco."""
 
    # 2. Hash da senha
    pwd_hash = get_password_hash(payload.password)
    
    # 3. Insere
    try:
        query = text("""
            INSERT INTO clients (phone_e164, name, birth_date, email, password_hash, created_at)
            VALUES (:phone, :name, :bdate, :email, :pwd, NOW())
            RETURNING id
        """)
        await db.execute(query, {
            "phone": payload.phone,
            "name": payload.name,
            "bdate": payload.birth_date,
            "email": payload.email,
            "pwd": pwd_hash
        })
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, "Erro ao criar conta. Telefone ou email já usados.")

    return {"message": "Conta criada! Faça login."}

@router.post("/login")
async def client_login_app(
    payload: ClientLoginRequest,
    db: AsyncSession = Depends(get_db_session)
):
    query = text("SELECT id, password_hash, fcm_token, is_blocked ,phone_e164,reputation FROM clients WHERE phone_e164 = :phone")
    result = await db.execute(query, {"phone": payload.phone})
    client = result.mappings().one_or_none()

    if not client:
        raise HTTPException(status_code=400, detail="Usuário não encontrado.")
    
    if client.is_blocked: raise HTTPException(403, "Conta bloqueada.")

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    # Verifica a senha (Hash)
    if not client['password_hash'] or not pwd_context.verify(payload.password, client['password_hash']):
        raise HTTPException(status_code=400, detail="Senha incorreta.")

# 3. ATUALIZAÇÃO DE LOCALIZAÇÃO E TOKEN (O PULO DO GATO 🐱)
    # Atualizamos lat, lon, o token FCM (caso tenha mudado de celular) e a hora do acesso.
    
    update_query = text("""
        UPDATE clients 
        SET 
            geog = ST_SetSRID(ST_MakePoint(:lat, :lon), 4326)::geography,
            fcm_token = :fcm,
            last_loc_at = NOW() ,
            actual_city = :city,
            actual_state = :state
        WHERE id = :id
    """)
    
    city_name = None
    state_name = None

    # Só busca se a lat/lon forem válidas
    if payload.lat != 0 and payload.lon != 0:
        address_info = get_address_from_coords(payload.lat, payload.lon)
        if address_info:
            city_name = address_info['city']
            state_name = address_info['state'] 
    # Só atualizamos se vieram coordenadas válidas (diferentes de 0)
    # Mas o fcm_token sempre atualizamos para garantir notificações
    try:
        if payload.lat != 0 or payload.lon != 0:
            address_info = get_address_from_coords(payload.lat, payload.lon)
            if address_info:
                city_name = address_info['city']
                state_name = address_info['state'] 
                await db.execute(update_query, {
                    "lat": payload.lat, 
                    "lon": payload.lon, 
                    "fcm": payload.fcm_token,
                    "id": client['id'],
                    "city": city_name,
                    "state": state_name
                })
                await db.commit()
                print(f"Localização do cliente {client['id']} atualizada: {payload.lat}, {payload.lon}")
            else:
                # Se a localização veio 0.0 (permissão negada), atualizamos pelo menos o token e o horário
                await db.execute(text("UPDATE clients SET fcm_token = :fcm, last_location_at = NOW() WHERE id = :id"), {
                "fcm": payload.fcm_token,
                "id": client['id']
                })
                await db.commit()

    except Exception as e:
        print(f"Erro ao atualizar localização no login: {e}")
        # Não damos raise error aqui para não impedir o login, apenas logamos o aviso.

    # 4. Retorna o Token
    fake_token = f"jwt_fake_{client['id']}_{payload.phone}"
    access_token = create_access_token(subject=client.id, extra_claims={"type": "client", "phone": client.phone_e164})
    return {"access_token": access_token, "token_type": "bearer", "client_id": client.id, "reputation": client.reputation}

@router.post("/token")
async def login_for_swagger(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: AsyncSession = Depends(get_db_session)
):
    """
    Rota exclusiva para o botão 'Authorize' do Swagger.
    O Swagger envia 'username', mas nós tratamos como 'phone'.
    """
    # 1. Busca o cliente pelo telefone (que vem no campo username)
    query = text("SELECT id, password_hash, phone_e164 FROM clients WHERE phone_e164 = :phone")
    result = await db.execute(query, {"phone": form_data.username})
    client = result.mappings().one_or_none()

    # 2. Validações
    if not client:
        raise HTTPException(status_code=400, detail="Usuário/Telefone incorreto")
    
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    if not client['password_hash'] or not pwd_context.verify(form_data.password, client['password_hash']):
        raise HTTPException(status_code=400, detail="Senha incorreta")

    # 3. Gera o Token (igual ao login normal)
    # Como é teste via Swagger, não atualizamos lat/lon/fcm aqui
    #access_token = f"jwt_fake_{client['id']}_{client['phone_e164']}"
    
    # O Swagger EXIGE que o retorno tenha exatamente esses campos:
    access_token = create_access_token(subject=client.id, extra_claims={"type": "client", "phone": client.phone_e164})
    return {"access_token": access_token, "token_type": "bearer"}