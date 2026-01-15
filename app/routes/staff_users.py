from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.perms_staff import require_admin
from app.schemas.staff_users import (
    StaffUserCreateRequest,
    StaffUserUpdateRequest,
    StaffUserResponse,
)

from app.integrations.resend_client import resend_send_email
from app.emails.staff_invite import build_staff_invite_email


router = APIRouter(prefix="/staff/users", tags=["staff-users"])


def _is_super_admin(staff: dict) -> bool:
    # Mantendo sua regra atual: restaurant_id == 1 => LetzIT internal
    # (Se você quiser migrar para role == INTERNAL_ADMIN depois, é só trocar aqui.)
    try:
        return int(staff["restaurant_id"]) == 1 or staff.get("role") == "INTERNAL_ADMIN"
    except Exception:
        return staff.get("role") == "INTERNAL_ADMIN"


# --- GET: LISTAR USUÁRIOS ---
@router.get("", response_model=list[StaffUserResponse])
async def list_staff_users(
    restaurant_id: Optional[int] = Query(None, description="Filtrar por restaurante (Apenas Super Admin)"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    require_admin(staff)

    logged_user_rid = int(staff["restaurant_id"])
    is_super_admin = _is_super_admin(staff)

    target_rid = logged_user_rid

    # Lógica de permissão:
    # - Super admin pode filtrar outros restaurantes
    # - Admin comum só lista do próprio restaurante
    if is_super_admin:
        if restaurant_id:
            target_rid = int(restaurant_id)
    else:
        if restaurant_id and int(restaurant_id) != logged_user_rid:
            raise HTTPException(
                status_code=403,
                detail="Você não tem permissão para visualizar a equipe de outros restaurantes.",
            )
        target_rid = logged_user_rid

    rows = (await db.execute(
        text("""
            SELECT id, restaurant_id, email, role, is_active, name, created_at, changed_at
            FROM restaurant_staff
            WHERE restaurant_id = :rid
            ORDER BY created_at DESC
        """),
        {"rid": target_rid},
    )).mappings().all()

    return [StaffUserResponse(**r) for r in rows]


# --- POST: CRIAR USUÁRIO (INATIVO + ENVIA CONVITE RESEND) ---
@router.post("", response_model=StaffUserResponse)
async def create_staff_user(
    payload: StaffUserCreateRequest,
    target_restaurant_id: Optional[int] = Query(None, description="ID do restaurante alvo (Apenas Super Admin)"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    require_admin(staff)

    logged_user_rid = int(staff["restaurant_id"])
    is_super_admin = _is_super_admin(staff)

    # 1) Restaurante alvo
    final_rid = logged_user_rid
    if is_super_admin:
        if target_restaurant_id:
            final_rid = int(target_restaurant_id)
    else:
        if target_restaurant_id and int(target_restaurant_id) != logged_user_rid:
            raise HTTPException(403, "Você só pode criar usuários para seu próprio restaurante.")

    # 2) Hierarquia: client admin não cria internal admin
    if (not is_super_admin) and payload.role == "INTERNAL_ADMIN":
        raise HTTPException(status_code=403, detail="Apenas a LetzIT pode criar novos INTERNAL_ADMIN.")

    # 3) Token/expiração (B: usuário define senha no link)
    token = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(hours=48)  # convite vale 48h

    # 4) Inserir INATIVO e SEM senha
    try:
        row = (await db.execute(
            text("""
                INSERT INTO restaurant_staff (
                    restaurant_id,
                    email,
                    ph,
                    role,
                    is_active,
                    name,
                    activation_token,
                    activation_expires_at,
                    created_at
                )
                VALUES (
                    :rid,
                    :email,
                    NULL,
                    :role,
                    false,
                    :name,
                    :tok,
                    :exp,
                    NOW()
                )
                RETURNING id, restaurant_id, email, role, is_active, name, created_at, changed_at
            """),
            {
                "rid": final_rid,
                "email": str(payload.email).lower(),
                "role": payload.role,
                "name": payload.name,
                "tok": str(token),
                "exp": expires,
            },
        )).mappings().first()

        await db.commit()

    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Este e-mail já está cadastrado neste restaurante.")

    # 5) Enviar email via Resend (fora da transação)
    # Pega nome do restaurante para deixar o email bonito
    rest = (await db.execute(
        text("SELECT name FROM restaurants WHERE id = :rid"),
        {"rid": final_rid},
    )).mappings().first()
    restaurant_name = rest["name"] if rest else "your restaurant"

    subject, html = build_staff_invite_email(
        restaurant_name=restaurant_name,
        token=str(token),
    )

    # Se o envio falhar, você pode decidir:
    # - manter usuário criado e retornar 200 (e criar endpoint de resend)
    # - ou retornar 500 e orientar a reenviar
    try:
        await resend_send_email(
            to=str(payload.email).lower(),
            subject=subject,
            html=html,
        )
    except Exception as e:
        # Mantém consistência do MVP: usuário criado, mas email falhou.
        # Você pode logar melhor isso depois.
        raise HTTPException(status_code=502, detail=f"User created but invite email failed: {str(e)}")

    return StaffUserResponse(**row)


# --- PATCH: ATUALIZAR USUÁRIO ---
@router.patch("/{staff_id}", response_model=StaffUserResponse)
async def update_staff_user(
    staff_id: int,
    payload: StaffUserUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    require_admin(staff)

    logged_user_rid = int(staff["restaurant_id"])
    is_super_admin = _is_super_admin(staff)

    # Proteção: não deixar desativar a si mesmo
    my_staff_id = int(staff.get("staff_id") or staff.get("id") or 0)
    if payload.is_active is False and staff_id == my_staff_id:
        raise HTTPException(status_code=400, detail="Você não pode desativar sua própria conta.")

    # Proteção: admin comum não promove para INTERNAL_ADMIN
    if (not is_super_admin) and payload.role == "INTERNAL_ADMIN":
        raise HTTPException(status_code=403, detail="Apenas a LetzIT pode definir INTERNAL_ADMIN.")

    sql = """
        UPDATE restaurant_staff
        SET
          role = COALESCE(:role, role),
          is_active = COALESCE(:is_active, is_active),
          name = COALESCE(:name, name),
          changed_at = NOW()
        WHERE id = :sid
    """

    params = {
        "sid": staff_id,
        "role": payload.role,
        "is_active": payload.is_active,
        "name": payload.name,
    }

    if not is_super_admin:
        sql += " AND restaurant_id = :rid"
        params["rid"] = logged_user_rid

    row = (await db.execute(
        text(sql + " RETURNING id, restaurant_id, email, role, is_active, name, created_at, changed_at"),
        params,
    )).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado ou sem permissão.")

    await db.commit()
    return StaffUserResponse(**row)
