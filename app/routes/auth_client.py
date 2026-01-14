from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.core.security import create_access_token
from app.schemas.client_auth import ClientLoginRequest

router = APIRouter(prefix="/client/auth", tags=["client-auth"])

@router.post("/login")
async def client_login(
    payload: ClientLoginRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Login via Telefone.
    - Se novo: Cria user com Level 1 e Reputação Inicial.
    - Se existente: Atualiza Geo, Data e Token FCM.
    """
    
    # 1. Query de UPSERT
    # Atualiza a localização sempre que o usuário loga
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
            fcm_token -- <--- ASSUMINDO QUE VOCÊ VAI TER ESSA COLUNA
        ) VALUES (
            :phone, 
            NOW(), 
            1,   -- Level inicial
            5.0, -- Reputação inicial (ou 0, como preferir)
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
            fcm_token = COALESCE(:fcm, users.fcm_token) -- Atualiza token se vier novo
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
        # Logar erro real aqui
        raise HTTPException(500, "Erro ao processar login do cliente.")

    # 2. Bloqueio de Segurança
    if user.is_blocked:
        raise HTTPException(403, "Sua conta está bloqueada. Entre em contato com o suporte.")

    # 3. Gera Token JWT
    # Diferente do Staff, o Client não tem role complexa ou restaurant_id
    access_token = create_access_token(
        subject=user.id,
        extra_claims={
            "type": "client", # Identifica que é usuário final
            "lvl": user.level # Útil para o frontend liberar features
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "reputation": user.reputation
    }
