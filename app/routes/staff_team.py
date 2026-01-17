from __future__ import annotations
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

# Imports Locais
from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.models import RestaurantStaff
from app.security import get_password_hash # Certifique-se de importar o hash
from app.schemas.staff import (
    StaffUserResponse, 
    InviteStaffRequest, 
    UpdateStaffRequest, 
    AdminResetPasswordRequest
)

router = APIRouter(prefix="/staff/team", tags=["Staff Team Management"])

# ==============================================================================
# HELPER: ENVIO DE EMAIL (MOCK)
# ==============================================================================
async def send_invite_email(email: str, name: str, token: str):
    link = f"https://letzit.com/activate?token={token}"
    print(f"📧 [EMAIL] Convite para {name} <{email}> | Link: {link}")

# ==============================================================================
# 1. LISTAR EQUIPE
# ==============================================================================
@router.get("", response_model=List[StaffUserResponse])
async def list_team_members(
    restaurant_id: Optional[int] = Query(None, description="Filtro para Super Admin"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    logged_rid = int(staff["restaurant_id"])
    target_rid = logged_rid

    # Lógica Super Admin
    if staff.get("role") == "INTERNAL_ADMIN" and logged_rid == 1 and restaurant_id:
        target_rid = restaurant_id

    stmt = select(RestaurantStaff).where(
        RestaurantStaff.restaurant_id == target_rid
    ).order_by(RestaurantStaff.created_at.desc())
    
    result = await db.execute(stmt)
    return result.scalars().all()

# ==============================================================================
# 2. CONVIDAR (INVITE)
# ==============================================================================
@router.post("/invite", response_model=StaffUserResponse)
async def invite_team_member(
    payload: InviteStaffRequest,
    restaurant_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    # Verificação de Permissão
    if staff.get("role") not in ["REST_ADMIN", "INTERNAL_ADMIN"]:
        raise HTTPException(403, "Apenas Admins podem convidar.")

    logged_rid = int(staff["restaurant_id"])
    target_rid = logged_rid

    if staff.get("role") == "INTERNAL_ADMIN" and logged_rid == 1 and restaurant_id:
        target_rid = restaurant_id
    
    if payload.role == "INTERNAL_ADMIN" and logged_rid != 1:
        raise HTTPException(403, "Você não pode criar Super Admins.")

    # 1. Check Duplicidade
    stmt_check = select(RestaurantStaff).where(RestaurantStaff.email == payload.email.lower())
    existing = (await db.execute(stmt_check)).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Este e-mail já está cadastrado.")

    # 2. Prepara Dados
    token = str(uuid4())
    expires = datetime.now(timezone.utc) + timedelta(hours=48)

    new_staff = RestaurantStaff(
        restaurant_id=target_rid,
        email=payload.email.lower(),
        role=payload.role,
        name=payload.name,
        is_active=False,
        password_hash=None, # Permitido pois mudamos o banco
        activation_token=token,
        activation_expires_at=expires,
        created_at=datetime.now(timezone.utc)
    )

    try:
        db.add(new_staff)
        await db.commit()
        await db.refresh(new_staff)
        
        await send_invite_email(new_staff.email, new_staff.name, token)
        return new_staff

    except IntegrityError:
        await db.rollback()
        raise HTTPException(400, "Erro ao criar usuário.")

# ==============================================================================
# 3. ATUALIZAR (UPDATE) - Refatorado para ORM
# ==============================================================================
@router.patch("/{staff_id}", response_model=StaffUserResponse)
async def update_team_member(
    staff_id: int,
    payload: UpdateStaffRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    if staff.get("role") not in ["REST_ADMIN", "INTERNAL_ADMIN"]:
        raise HTTPException(403, "Sem permissão.")

    # Busca o usuário alvo
    stmt = select(RestaurantStaff).where(RestaurantStaff.id == staff_id)
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(404, "Funcionário não encontrado.")

    # Validação de acesso a outros restaurantes
    logged_rid = int(staff["restaurant_id"])
    if target_user.restaurant_id != logged_rid and staff.get("role") != "INTERNAL_ADMIN":
         raise HTTPException(403, "Você só pode editar sua própria equipe.")

    # Bloqueio: não desativar a si mesmo
    if int(staff["id"]) == staff_id and payload.is_active is False:
        raise HTTPException(400, "Você não pode desativar sua própria conta.")

    # Atualização Pythonica (ORM)
    if payload.name is not None:
        target_user.name = payload.name
    if payload.role is not None:
        target_user.role = payload.role
    if payload.is_active is not None:
        target_user.is_active = payload.is_active
    
    target_user.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(target_user)
    return target_user

# ==============================================================================
# 4. RESET SENHA (ADMIN) - Refatorado para ORM
# ==============================================================================
@router.post("/{staff_id}/reset-password")
async def admin_reset_password(
    staff_id: int,
    payload: AdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    if staff.get("role") not in ["REST_ADMIN", "INTERNAL_ADMIN"]:
        raise HTTPException(403, "Sem permissão.")

    stmt = select(RestaurantStaff).where(RestaurantStaff.id == staff_id)
    target_user = (await db.execute(stmt)).scalar_one_or_none()

    if not target_user:
        raise HTTPException(404, "Funcionário não encontrado.")

    # Segurança Super Admin
    if target_user.role == "INTERNAL_ADMIN" and staff.get("role") != "INTERNAL_ADMIN":
        raise HTTPException(403, "Você não pode resetar senha de um Super Admin.")

    target_user.password_hash = get_password_hash(payload.new_password)
    target_user.updated_at = datetime.now(timezone.utc)
    
    await db.commit()

    return {"message": f"Senha de {target_user.name} foi alterada."}

# ==============================================================================
# 5. REMOVER (DELETE)
# ==============================================================================
@router.delete("/{staff_id}")
async def remove_team_member(
    staff_id: int,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    if staff.get("role") not in ["REST_ADMIN", "INTERNAL_ADMIN"]:
        raise HTTPException(403, "Sem permissão.")
    
    stmt = select(RestaurantStaff).where(RestaurantStaff.id == staff_id)
    target_user = (await db.execute(stmt)).scalar_one_or_none()

    if not target_user:
        raise HTTPException(404, "Funcionário não encontrado.")
    
    # Validações de segurança (mesmo restaurante, não se deletar)...
    if target_user.restaurant_id != int(staff["restaurant_id"]) and staff.get("role") != "INTERNAL_ADMIN":
        raise HTTPException(403, "Acesso negado.")

    if target_user.id == int(staff["id"]):
        raise HTTPException(400, "Você não pode remover a si mesmo.")

    await db.delete(target_user)
    await db.commit()

    return {"message": "Funcionário removido."}