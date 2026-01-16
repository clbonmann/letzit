from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.security import verify_password, create_access_token, get_password_hash
# IMPORTANDO SCHEMAS
from app.schemas.staff import (
    StaffLoginRequest, StaffLoginResponse, StaffMeResponse, 
    ActivationPreviewResponse, ActivateAccountRequest, ChangePasswordRequest
)

router = APIRouter(prefix="/staff/auth", tags=["staff-auth"])

@router.post("/login", response_model=StaffLoginResponse)
async def login(payload: StaffLoginRequest, db: AsyncSession = Depends(get_db_session)):
    query = text("SELECT id, name, email, password_hash, role, restaurant_id, is_active FROM restaurant_staff WHERE lower(email) = lower(:email)")
    staff = (await db.execute(query, {"email": payload.email})).mappings().first()

    if not staff: raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas")
    if not staff.is_active: raise HTTPException(status.HTTP_403_FORBIDDEN, "Conta pendente de ativação.")
    if not verify_password(payload.password, staff.password_hash): raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas")

    access_token = create_access_token(subject=str(staff.id), extra_claims={"role": staff.role, "rid": int(staff.restaurant_id)})
    return StaffLoginResponse(access_token=access_token, staff_id=staff.id, name=staff.name or "", role=staff.role, restaurant_id=staff.restaurant_id)

@router.get("/me", response_model=StaffMeResponse)
async def get_me(staff: dict = Depends(get_current_staff)):
    return StaffMeResponse(id=int(staff["id"]), restaurant_id=int(staff["restaurant_id"]), email=staff["email"], role=staff.get("role", ""), name=staff.get("name"))

@router.get("/activation-preview", response_model=ActivationPreviewResponse)
async def preview_activation(token: UUID, db: AsyncSession = Depends(get_db_session)):
    row = (await db.execute(text("SELECT email, name, is_active, activation_expires_at FROM restaurant_staff WHERE activation_token = :tok"), {"tok": str(token)})).mappings().first()
    if not row: raise HTTPException(400, "Token inválido.")
    if row.is_active: raise HTTPException(409, "Conta já ativada.")
    if row.activation_expires_at and row.activation_expires_at < datetime.now(timezone.utc): raise HTTPException(400, "Link expirado.")
    return ActivationPreviewResponse(email=row.email, name=row.name)

@router.post("/activate")
async def activate_account(payload: ActivateAccountRequest, db: AsyncSession = Depends(get_db_session)):
    now = datetime.now(timezone.utc)
    row = (await db.execute(text("SELECT id, is_active, activation_expires_at FROM restaurant_staff WHERE activation_token = :tok FOR UPDATE"), {"tok": str(payload.token)})).mappings().first()
    if not row: raise HTTPException(400, "Token inválido.")
    if row.is_active: raise HTTPException(409, "Conta já ativada.")
    if row.activation_expires_at and row.activation_expires_at < now: raise HTTPException(400, "Link expirado.")

    await db.execute(text("UPDATE restaurant_staff SET password_hash = :ph, is_active = true, activated_at = :now, activation_token = NULL, activation_expires_at = NULL WHERE id = :sid"), {"ph": get_password_hash(payload.password), "now": now, "sid": row.id})
    await db.commit()
    return {"status": "ACTIVATED", "staff_id": row.id}

@router.post("/change-password")
async def change_own_password(payload: ChangePasswordRequest, db: AsyncSession = Depends(get_db_session), current_staff: dict = Depends(get_current_staff)):
    row = (await db.execute(text("SELECT password_hash FROM restaurant_staff WHERE id = :uid"), {"uid": int(current_staff["id"])})).mappings().first()
    if not row or not verify_password(payload.old_password, row.password_hash): raise HTTPException(400, "Senha atual incorreta.")
    
    await db.execute(text("UPDATE restaurant_staff SET password_hash = :ph WHERE id = :uid"), {"ph": get_password_hash(payload.new_password), "uid": int(current_staff["id"])})
    await db.commit()
    return {"message": "Senha alterada."}
