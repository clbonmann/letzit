from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.deps_client import get_current_user_id 
# IMPORTANDO OS SCHEMAS
from app.schemas.client import UserProfileResponse, UserUpdateProfileRequest, LocationUpdateSchema

router = APIRouter(prefix="/client/profile", tags=["client-profile"])

@router.get("", response_model=UserProfileResponse)
async def get_my_profile(
    uid: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
):
    """Retorna dados do usuário logado."""
    query = text("SELECT id, name, phone_e164 as phone, email, avatar_url, reputation, level, created_at FROM users WHERE id = :uid")
    row = (await db.execute(query, {"uid": uid})).mappings().first()
    if not row: raise HTTPException(404, "Usuário não encontrado.")
    return UserProfileResponse(**row)

@router.patch("", response_model=UserProfileResponse)
async def update_my_profile(
    payload: UserUpdateProfileRequest,
    uid: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
):
    """Atualiza dados cadastrais."""
    fields, params = [], {"uid": uid}
    if payload.name: fields.append("name = :name"); params["name"] = payload.name
    if payload.email: fields.append("email = :email"); params["email"] = payload.email
    if payload.avatar_url: fields.append("avatar_url = :avatar"); params["avatar"] = payload.avatar_url
    
    if not fields: return await get_my_profile(uid, db)
    
    fields.append("updated_at = NOW()")
    query = text(f"UPDATE users SET {', '.join(fields)} WHERE id = :uid RETURNING id, name, phone_e164 as phone, email, avatar_url, reputation, level, created_at")
    
    try:
        row = (await db.execute(query, params)).mappings().first()
        await db.commit()
        return UserProfileResponse(**row)
    except Exception:
        await db.rollback()
        raise HTTPException(500, "Erro ao atualizar perfil.")

@router.post("/location")
async def update_location(
    location_data: LocationUpdateSchema,
    uid: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
):
    """Atualiza GPS."""
    await db.execute(
        text("UPDATE users SET geog = ST_SetSRID(ST_MakePoint(:long, :lat), 4326)::geography, last_loc_at = NOW(), loc_accuracy_m = :acc WHERE id = :uid"),
        {"lat": location_data.latitude, "long": location_data.longitude, "acc": location_data.accuracy, "uid": uid}
    )
    await db.commit()
    return {"status": "updated", "timestamp": datetime.now(timezone.utc)}

@router.delete("")
async def delete_account(
    uid: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
):
    """Exclusão de conta."""
    try:
        await db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(500, "Erro ao excluir conta.")
    return {"message": "Conta excluída."}

