from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
# Ajuste os imports de segurança conforme seus arquivos utilitários
from app.security import verify_password, create_access_token, hash_password 

router = APIRouter(prefix="/staff/auth", tags=["staff-auth"])

# --- SCHEMAS ---

class StaffLoginRequest(BaseModel):
    email: EmailStr
    password: str

class StaffLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff_id: int
    name: str
    role: str
    restaurant_id: int

class StaffMeResponse(BaseModel):
    id: int
    restaurant_id: int
    email: str
    role: str
    name: str | None

class ActivationPreviewResponse(BaseModel):
    status: str = "PENDING"
    email: EmailStr
    name: str | None = None

class ActivateAccountRequest(BaseModel):
    token: UUID
    password: str = Field(..., min_length=6, max_length=100)

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=100)

# --- ENDPOINTS ---

@router.post("/login", response_model=StaffLoginResponse)
async def login(
    payload: StaffLoginRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Login padrão. Verifica credenciais e se a conta está ativa.
    """
    query = text("""
        SELECT id, name, email, password_hash, role, restaurant_id, is_active
        FROM restaurant_staff
        WHERE lower(email) = lower(:email)
    """)
    user = (await db.execute(query, {"email": payload.email})).mappings().first()

    if not user:
        # Retorna 401 genérico para segurança
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas")

    if not bool(user["is_active"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Conta pendente de ativação. Verifique seu e-mail.")

    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas")

    # Gera Token JWT com claims úteis
    access_token = create_access_token(
        subject=str(user["id"]),
        extra_claims={
            "role": user["role"],
            "rid": int(user["restaurant_id"])
        }
    )

    return StaffLoginResponse(
        access_token=access_token,
        staff_id=user["id"],
        name=user["name"] or "",
        role=user["role"] or "",
        restaurant_id=user["restaurant_id"]
    )


@router.get("/me", response_model=StaffMeResponse)
async def get_me(staff: dict = Depends(get_current_staff)):
    """Retorna dados do usuário logado."""
    return StaffMeResponse(
        id=int(staff["id"]),
        restaurant_id=int(staff["restaurant_id"]),
        email=staff["email"],
        role=staff.get("role", ""),
        name=staff.get("name")
    )


@router.get("/activation-preview", response_model=ActivationPreviewResponse)
async def preview_activation(
    token: UUID,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Check de segurança: Frontend chama isso ao carregar a página de "Definir Senha".
    Valida se o token existe e não expirou antes de deixar o usuário digitar a senha.
    """
    now = datetime.now(timezone.utc)
    
    row = (await db.execute(
        text("""
            SELECT email, name, is_active, activation_expires_at
            FROM restaurant_staff
            WHERE activation_token = :tok
        """),
        {"tok": str(token)},
    )).mappings().first()

    if not row:
        raise HTTPException(400, "Token inválido.")
    
    if bool(row["is_active"]):
        raise HTTPException(409, "Conta já ativada. Faça login.")

    if row["activation_expires_at"] and row["activation_expires_at"] < now:
        raise HTTPException(400, "Link de ativação expirado. Peça um novo convite ao gerente.")

    return ActivationPreviewResponse(
        email=row["email"],
        name=row["name"]
    )


@router.post("/activate")
async def activate_account(
    payload: ActivateAccountRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Finaliza o cadastro: Define a senha inicial e ativa a conta.
    """
    now = datetime.now(timezone.utc)

    # Busca com Lock para evitar race conditions
    row = (await db.execute(
        text("""
            SELECT id, is_active, activation_expires_at
            FROM restaurant_staff
            WHERE activation_token = :tok
            FOR UPDATE
        """),
        {"tok": str(payload.token)},
    )).mappings().first()

    if not row:
        raise HTTPException(400, "Token inválido.")
    
    if bool(row["is_active"]):
        raise HTTPException(409, "Conta já ativada.")

    if row["activation_expires_at"] and row["activation_expires_at"] < now:
        raise HTTPException(400, "Link expirado.")

    # Hash da nova senha
    new_hash = hash_password(payload.password)

    # Correção: O nome da coluna no banco provavelmente é password_hash, não 'ph'
    await db.execute(
        text("""
            UPDATE restaurant_staff
            SET password_hash = :ph,
                is_active = true,
                activated_at = :now,
                activation_token = NULL,
                activation_expires_at = NULL
            WHERE id = :sid
        """),
        {"ph": new_hash, "now": now, "sid": row["id"]}
    )
    await db.commit()

    return {"status": "ACTIVATED", "staff_id": row["id"]}


@router.post("/change-password")
async def change_own_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db_session),
    current_staff: dict = Depends(get_current_staff)
):
    """
    Self-Service: O usuário logado troca a PRÓPRIA senha.
    Exige confirmação da senha antiga.
    """
    staff_id = int(current_staff["id"])

    # 1. Busca a senha atual (hash)
    row = (await db.execute(
        text("SELECT password_hash FROM restaurant_staff WHERE id = :uid"),
        {"uid": staff_id}
    )).mappings().first()

    if not row:
        raise HTTPException(404, "Usuário não encontrado.")

    # 2. Verifica senha antiga
    if not verify_password(payload.old_password, row["password_hash"]):
        raise HTTPException(400, "A senha atual está incorreta.")

    # 3. Salva nova senha
    new_hash = hash_password(payload.new_password)
    
    await db.execute(
        text("UPDATE restaurant_staff SET password_hash = :ph WHERE id = :uid"),
        {"ph": new_hash, "uid": staff_id}
    )
    await db.commit()

    return {"message": "Senha alterada com sucesso."}
