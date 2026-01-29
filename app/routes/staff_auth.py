from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Imports do seu projeto
from app.db import get_db_session
from app.deps_staff import get_current_staff # Ajuste se o nome do arquivo for deps_staff
from app.security import verify_password, create_access_token, get_password_hash # Ajuste seus imports de segurança
from app.models import StoreStaff # Importante: Importar o Model do Banco

# Imports dos Schemas (Pydantic)
from app.schemas.staff import (
    StaffLoginRequest, 
    StaffLoginResponse, 
    StaffMeResponse, 
    ActivationPreviewResponse, 
    ActivateAccountRequest, 
    ChangePasswordRequest
)

router = APIRouter(prefix="/staff/auth", tags=["Staff Auth"])

# ==============================================================================
# 1. LOGIN
# ==============================================================================
@router.post("/login", response_model=StaffLoginResponse)
async def login(
    payload: StaffLoginRequest, 
    db: AsyncSession = Depends(get_db_session)
):
    # Busca o usuário pelo email (case insensitive)
    stmt = select(StoreStaff).where(
        StoreStaff.email == payload.email.lower()
    )
    result = await db.execute(stmt)
    staff = result.scalar_one_or_none()

    # 1. Verifica se usuário existe
    if not staff:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas")
    
    # 2. Verifica se a conta está ativa (Crucial para o fluxo de convite)
    if not staff.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Conta pendente de ativação. Verifique seu e-mail.")

    # 3. Verifica a senha
    # Nota: Se password_hash for None (banco), verify_password deve lidar ou falhar seguro.
    if not staff.password_hash or not verify_password(payload.password, staff.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas")

    # 4. Gera o Token JWT
    access_token = create_access_token(
        subject=str(staff.id), 
        extra_claims={
            "role": staff.role, 
            "rid": int(staff.store_id),
            "staff_id": int(staff.id)
        }
    )

    return StaffLoginResponse(
        access_token=access_token, 
        staff_id=staff.id, 
        name=staff.name or "", 
        role=staff.role, 
        store_id=staff.store_id
    )

# ==============================================================================
# 2. GET ME (Dados do usuário logado)
# ==============================================================================
@router.get("/me", response_model=StaffMeResponse)
async def get_me(staff: dict = Depends(get_current_staff)):
    # O middleware get_current_staff já decodificou o token
    return StaffMeResponse(
        id=int(staff["id"]), # Garante que usa o ID do payload do token
        store_id=int(staff["store_id"]),
        email=staff["email"],
        role=staff.get("role", ""),
        name=staff.get("name", "")
    )

# ==============================================================================
# 3. PREVIEW DA ATIVAÇÃO (Chamado pelo Frontend ao abrir o link)
# ==============================================================================
@router.get("/activation-preview", response_model=ActivationPreviewResponse)
async def preview_activation(
    token: str, # Pode ser UUID, mas str é mais flexível na URL
    db: AsyncSession = Depends(get_db_session)
):
    # Busca pelo token
    stmt = select(StoreStaff).where(StoreStaff.activation_token == str(token))
    result = await db.execute(stmt)
    staff_user = result.scalar_one_or_none()

    if not staff_user:
        raise HTTPException(400, "Token inválido ou usuário não encontrado.")

    if staff_user.is_active:
        raise HTTPException(409, "Esta conta já foi ativada. Faça login.")

    # Verifica expiração
    now = datetime.now(timezone.utc)
    if staff_user.activation_expires_at and staff_user.activation_expires_at < now:
        raise HTTPException(400, "Este link de convite expirou. Solicite um novo ao administrador.")

    return ActivationPreviewResponse(
        email=staff_user.email, 
        name=staff_user.name
    )

# ==============================================================================
# 4. ATIVAR CONTA (Salva a senha)
# ==============================================================================
@router.post("/activate")
async def activate_account(
    payload: ActivateAccountRequest, 
    db: AsyncSession = Depends(get_db_session)
):
    # Busca pelo token novamente (segurança dupla)
    stmt = select(StoreStaff).where(
        StoreStaff.activation_token == str(payload.token)
    )
    result = await db.execute(stmt)
    staff_user = result.scalar_one_or_none()

    if not staff_user:
        raise HTTPException(400, "Token inválido.")
    
    if staff_user.is_active:
        raise HTTPException(409, "Conta já ativada.")

    # Atualiza os dados usando o objeto ORM
    staff_user.password_hash = get_password_hash(payload.password)
    staff_user.is_active = True
    staff_user.activated_at = datetime.now(timezone.utc)
    
    # Limpa o token para não ser usado novamente
    staff_user.activation_token = None
    staff_user.activation_expires_at = None

    await db.commit()
    # Não precisa de refresh se não formos retornar o objeto completo, 
    # mas garante que salvou sem erro.
    
    return {
        "status": "ACTIVATED", 
        "staff_id": staff_user.id,
        "message": "Conta ativada com sucesso."
    }

# ==============================================================================
# 5. TROCAR SENHA (Usuário logado)
# ==============================================================================
@router.post("/change-password")
async def change_own_password(
    payload: ChangePasswordRequest, 
    db: AsyncSession = Depends(get_db_session), 
    current_staff: dict = Depends(get_current_staff)
):
    # Busca o usuário no banco para pegar o hash atual
    stmt = select(StoreStaff).where(
        StoreStaff.id == int(current_staff["id"])
    )
    result = await db.execute(stmt)
    staff_user = result.scalar_one_or_none()

    if not staff_user:
        raise HTTPException(404, "Usuário não encontrado.")

    # Verifica a senha antiga
    if not verify_password(payload.old_password, staff_user.password_hash):
        raise HTTPException(400, "A senha atual está incorreta.")
    
    # Atualiza para a nova senha
    staff_user.password_hash = get_password_hash(payload.new_password)
    
    await db.commit()
    
    return {"message": "Senha alterada com sucesso."}