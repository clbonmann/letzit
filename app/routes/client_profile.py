from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
# Importante: Usamos o deps_user que criamos para validar o token do CLIENTE
from app.deps_user import get_current_user_id 

router = APIRouter(prefix="/client/profile", tags=["client-profile"])

# --- SCHEMAS ---

class UserProfileResponse(BaseModel):
    id: int
    name: str | None
    phone: str
    email: str | None
    avatar_url: str | None
    reputation: float
    level: int
    created_at: datetime
    # Não retornamos dados sensíveis ou geográficos aqui

class UserUpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    avatar_url: Optional[str] = None

class LocationUpdateSchema(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = 0.0 # Campo opcional útil para filtrar GPS ruim

# --- ENDPOINTS ---

@router.get("", response_model=UserProfileResponse)
async def get_my_profile(
    uid: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Retorna os dados do usuário logado para a tela 'Minha Conta'.
    """
    query = text("""
        SELECT id, name, phone_e164 as phone, email, avatar_url, reputation, level, created_at
        FROM users
        WHERE id = :uid
    """)
    
    row = (await db.execute(query, {"uid": uid})).mappings().first()
    
    if not row:
        raise HTTPException(404, "Usuário não encontrado.")
        
    return UserProfileResponse(**row)


@router.patch("", response_model=UserProfileResponse)
async def update_my_profile(
    payload: UserUpdateProfileRequest,
    uid: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Atualiza dados cadastrais (Nome, Email, Foto).
    """
    # Monta query dinâmica (só atualiza o que foi enviado)
    fields = []
    params = {"uid": uid}
    
    if payload.name is not None:
        fields.append("name = :name")
        params["name"] = payload.name
        
    if payload.email is not None:
        fields.append("email = :email")
        params["email"] = payload.email
        
    if payload.avatar_url is not None:
        fields.append("avatar_url = :avatar")
        params["avatar"] = payload.avatar_url
        
    if not fields:
        # Se não mandou nada, retorna o perfil sem alterar
        return await get_my_profile(uid, db)
    
    # Adicionamos timestamp de atualização
    fields.append("updated_at = NOW()")

    query = text(f"""
        UPDATE users 
        SET {', '.join(fields)} 
        WHERE id = :uid
        RETURNING id, name, phone_e164 as phone, email, avatar_url, reputation, level, created_at
    """)
    
    try:
        row = (await db.execute(query, params)).mappings().first()
        await db.commit()
        return UserProfileResponse(**row)
    except Exception as e:
        await db.rollback()
        # Logar erro real aqui
        raise HTTPException(500, "Erro ao atualizar perfil.")


@router.post("/location") # Mudei para POST por ser padrão de envio de telemetria, mas pode ser PUT
async def update_location(
    location_data: LocationUpdateSchema,
    uid: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Atualiza a geolocalização do usuário.
    Essencial para o funcionamento das ofertas por proximidade.
    """
    # Query corrigida (Adicionei a vírgula que faltava e o campo accuracy)
    await db.execute(
        text("""
            UPDATE users 
            SET 
                geog = ST_SetSRID(ST_MakePoint(:long, :lat), 4326)::geography, 
                last_loc_at = NOW(),
                loc_accuracy_m = :acc
            WHERE id = :uid
        """),
        {
            "lat": location_data.latitude,
            "long": location_data.longitude,
            "acc": location_data.accuracy,
            "uid": uid
        }
    )
    await db.commit()
    
    return {"status": "updated", "timestamp": datetime.now(timezone.utc)}


@router.delete("")
async def delete_account(
    uid: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Exclusão de conta (Obrigatório para conformidade com App Stores).
    """
    try:
        # Hard Delete: Remove o usuário. 
        # O banco deve estar configurado com ON DELETE CASCADE nas chaves estrangeiras 
        # (offer_targets, claims, etc) para limpar tudo automaticamente.
        await db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, "Erro ao excluir conta.")

    return {"message": "Conta excluída permanentemente."}
