from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.perms_staff import require_admin
# Certifique-se de importar seu utilitário de hash
from app.security import hash_password 

router = APIRouter(prefix="/staff/team", tags=["staff-team"])

# --- SCHEMAS ---

class StaffUserResponse(BaseModel):
    id: int
    restaurant_id: int
    email: str
    name: str | None
    role: str
    is_active: bool
    created_at: datetime
    # activation_token não é retornado por segurança, a menos que explicitamente necessário

class InviteStaffRequest(BaseModel):
    email: EmailStr
    name: str
    role: str = Field(..., description="MANAGER, WAITER, KITCHEN")

class UpdateStaffRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6)

# --- HELPER: PERMISSÕES ---
def get_target_restaurant_id(staff: dict, query_rid: Optional[int]) -> int:
    """
    Define qual restaurante está sendo manipulado.
    - Se for INTERNAL_ADMIN (ID 1), pode passar query_rid para mexer em outros.
    - Se for Admin Normal, só pode mexer no seu próprio.
    """
    logged_rid = int(staff["restaurant_id"])
    is_super = (logged_rid == 1) # Regra Hardcoded para LetzIT Admin

    if is_super and query_rid:
        return query_rid
    
    if query_rid and query_rid != logged_rid:
        raise HTTPException(403, "Você não tem permissão para gerenciar equipes de outros restaurantes.")
        
    return logged_rid

# --- ENDPOINTS ---

@router.get("", response_model=List[StaffUserResponse])
async def list_team_members(
    restaurant_id: Optional[int] = Query(None, description="Filtro para Super Admin"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Lista todos os membros da equipe do restaurante.
    """
    target_rid = get_target_restaurant_id(staff, restaurant_id)

    query = text("""
        SELECT id, restaurant_id, email, name, role, is_active, created_at
        FROM restaurant_staff
        WHERE restaurant_id = :rid
        ORDER BY created_at DESC
    """)
    
    rows = (await db.execute(query, {"rid": target_rid})).mappings().all()
    return [StaffUserResponse(**r) for r in rows]


@router.post("/invite", response_model=StaffUserResponse)
async def invite_team_member(
    payload: InviteStaffRequest,
    restaurant_id: Optional[int] = Query(None, description="Alvo para Super Admin"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Cria um novo funcionário (Convite).
    Gera um token de ativação para que ele defina a senha depois.
    """
    require_admin(staff) # Apenas Gerentes/Admins podem convidar
    target_rid = get_target_restaurant_id(staff, restaurant_id)
    logged_rid = int(staff["restaurant_id"])

    # Segurança: Ninguém além do Super Admin cria outro INTERNAL_ADMIN
    if payload.role == "INTERNAL_ADMIN" and logged_rid != 1:
        raise HTTPException(403, "Apenas a LetzIT pode criar Super Admins.")

    # Gera Token de Ativação (48 horas de validade)
    token = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(hours=48)

    try:
        row = (await db.execute(
            text("""
                INSERT INTO restaurant_staff (
                    restaurant_id, email, role, name, 
                    is_active, password_hash, 
                    activation_token, activation_expires_at, created_at
                )
                VALUES (
                    :rid, :email, :role, :name, 
                    FALSE, NULL, 
                    :tok, :exp, NOW()
                )
                RETURNING id, restaurant_id, email, name, role, is_active, created_at
            """),
            {
                "rid": target_rid,
                "email": payload.email.lower(),
                "role": payload.role,
                "name": payload.name,
                "tok": str(token),
                "exp": expires
            }
        )).mappings().first()
        
        await db.commit()
        
        # TODO: Aqui entraria o disparo de e-mail (SendGrid/AWS SES) com o link:
        # link = f"https://app.letzit.com/staff/activate?token={token}"
        # print(f"DEBUG: Link de convite gerado: {link}")

        return StaffUserResponse(**row)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Este e-mail já está cadastrado na equipe.")


@router.patch("/{staff_id}", response_model=StaffUserResponse)
async def update_team_member(
    staff_id: int,
    payload: UpdateStaffRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Atualiza dados de um membro (Nome, Cargo, Ativar/Desativar).
    """
    require_admin(staff)
    
    # Busca usuário alvo para validar se pertence ao mesmo restaurante
    target_user = (await db.execute(
        text("SELECT restaurant_id FROM restaurant_staff WHERE id = :sid"),
        {"sid": staff_id}
    )).mappings().first()

    if not target_user:
        raise HTTPException(404, "Funcionário não encontrado.")

    # Valida se o Admin tem permissão sobre esse restaurante
    # (Se não passou query param, assume o do usuário alvo para validar)
    get_target_restaurant_id(staff, target_user.restaurant_id)

    # Proteção: Não se desativar
    if int(staff["id"]) == staff_id and payload.is_active is False:
        raise HTTPException(400, "Você não pode desativar sua própria conta.")

    # Executa Update Dinâmico
    try:
        row = (await db.execute(
            text("""
                UPDATE restaurant_staff
                SET
                    name = COALESCE(:name, name),
                    role = COALESCE(:role, role),
                    is_active = COALESCE(:active, is_active),
                    updated_at = NOW()
                WHERE id = :sid
                RETURNING id, restaurant_id, email, name, role, is_active, created_at
            """),
            {
                "sid": staff_id,
                "name": payload.name,
                "role": payload.role,
                "active": payload.is_active
            }
        )).mappings().first()
        
        await db.commit()
        return StaffUserResponse(**row)
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, "Erro ao atualizar funcionário.")


@router.post("/{staff_id}/reset-password")
async def admin_reset_password(
    staff_id: int,
    payload: AdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Função Administrativa: O Gerente reseta a senha de um funcionário que esqueceu.
    Define a nova senha diretamente (sem token).
    """
    require_admin(staff)

    # Busca usuário alvo
    target_user = (await db.execute(
        text("SELECT restaurant_id, role FROM restaurant_staff WHERE id = :sid"),
        {"sid": staff_id}
    )).mappings().first()

    if not target_user:
        raise HTTPException(404, "Funcionário não encontrado.")

    # Valida permissão de restaurante
    get_target_restaurant_id(staff, target_user.restaurant_id)

    # Proteção de Hierarquia: Client Admin não reseta senha de Super Admin
    logged_role = staff.get("role")
    if logged_role != "INTERNAL_ADMIN" and target_user.role == "INTERNAL_ADMIN":
        raise HTTPException(403, "Você não tem permissão para alterar senha de um Super Admin.")

    # Atualiza a senha
    new_hash = hash_password(payload.new_password)
    
    await db.execute(
        text("UPDATE restaurant_staff SET password_hash = :ph, updated_at = NOW() WHERE id = :sid"),
        {"ph": new_hash, "sid": staff_id}
    )
    await db.commit()

    return {"message": f"Senha do funcionário ID {staff_id} foi resetada com sucesso."}
