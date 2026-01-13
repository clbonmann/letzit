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
from app.security import hash_password
from app.perms_staff import require_admin
from app.schemas.staff_users import (
    StaffUserCreateRequest,
    StaffUserUpdateRequest,
    StaffUserResponse,
)

router = APIRouter(prefix="/staff/users", tags=["staff-users"])


@router.get("", response_model=list[StaffUserResponse])
async def list_staff_users(
    # 1. Adicionamos o parâmetro opcional na Query String
    restaurant_id: Optional[int] = Query(None, description="Filtrar por restaurante (Apenas Super Admin)"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    # require_admin(staff) -> Cuidado: garanta que essa função não bloqueie o Super Admin
    
    logged_user_rid = int(staff["restaurant_id"])
    
    # Verificação de Super Admin (Assumindo que ID 1 é a LetzIT)
    # Se você já tiver staff["is_super_admin"] na dependencia, use-a.
    is_super_admin = (logged_user_rid == 1) 

    target_rid = logged_user_rid # O padrão é ver o próprio restaurante

    # --- LÓGICA DE SEGURANÇA (RBAC) ---
    if is_super_admin:
        # Se é o chefe, e ele passou um ID na URL, usamos esse ID.
        if restaurant_id:
            target_rid = restaurant_id
    else:
        # Se é um restaurante comum tentando ver outro:
        if restaurant_id and restaurant_id != logged_user_rid:
            raise HTTPException(
                status_code=403, 
                detail="Você não tem permissão para visualizar a equipe de outros restaurantes."
            )
        # Força o ID do token, ignorando o parametro
        target_rid = logged_user_rid

    # --- QUERY ---
    rows = (await db.execute(
        text("""
            SELECT id, restaurant_id, email, role, is_active, name, created_at, changed_at
            FROM restaurant_staff -- Confirme se o nome da tabela é 'staff' ou 'restaurant_staff'
            WHERE restaurant_id = :rid
            ORDER BY created_at DESC
        """),
        {"rid": target_rid},
    )).mappings().all()

    return [StaffUserResponse(**r) for r in rows]
    
@router.post("", response_model=StaffUserResponse)    
async def create_staff_user(
    payload: StaffUserCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    require_admin(staff)
    rid = int(staff["restaurant_id"])

    # CLIENT_ADMIN não deveria criar INTERNAL_ADMIN
    if staff.get("role") != "INTERNAL_ADMIN" and payload.role == "INTERNAL_ADMIN":
        raise HTTPException(status_code=403, detail="Only INTERNAL_ADMIN can create INTERNAL_ADMIN")

    ph = null()

    try:
        row = (await db.execute(
            text("""
              INSERT INTO restaurant_staff (
              restaurant_id, email, ph, role, is_active, name,
              activation_token, activation_expires_at
              )
              VALUES (:rid, :email, :ph, :role, false, :name, :tok, :exp)
              RETURNING id, restaurant_id, email, role, is_active, name, created_at, changed_at
             """),
            {
             "rid": rid,
             "email": str(payload.email).lower(),
             "ph": ph,
             "role": payload.role,
             "name": payload.name,
             "tok": str(token),
             "exp": expires,
           },
           )
        ).mappings().first()

        await db.commit()
        # TODO: enviar email com link contendo token
        # activation_link = f"{settings.STAFF_ACTIVATION_BASE_URL}?token={token}"
        return StaffUserResponse(**row)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Staff email already exists for this restaurant")


@router.patch("/{staff_id}", response_model=StaffUserResponse)
async def update_staff_user(
    staff_id: int,
    payload: StaffUserUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    require_admin(staff)
    rid = int(staff["restaurant_id"])

    # não deixar o admin desativar ele mesmo (opcional, mas recomendado)
    my_staff_id = int(staff.get("staff_id") or staff.get("id") or 0)
    if payload.is_active is False and staff_id == my_staff_id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    # CLIENT_ADMIN não pode promover ninguém para INTERNAL_ADMIN
    if staff.get("role") != "INTERNAL_ADMIN" and payload.role == "INTERNAL_ADMIN":
        raise HTTPException(status_code=403, detail="Only INTERNAL_ADMIN can assign INTERNAL_ADMIN")

    row = (await db.execute(
        text("""
            UPDATE restaurant_staff
            SET
              role = COALESCE(:role, role),
              is_active = COALESCE(:is_active, is_active),
              name = COALESCE(:name, name)
            WHERE id = :sid AND restaurant_id = :rid
            RETURNING id, restaurant_id, email, role, is_active, name, created_at, changed_at
        """),
        {
            "sid": staff_id,
            "rid": rid,
            "role": payload.role,
            "is_active": payload.is_active,
            "name": payload.name,
        },
    )).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Staff user not found")

    await db.commit()
    return StaffUserResponse(**row)
