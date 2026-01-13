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

router = APIRouter(prefix="/staff/users", tags=["staff-users"])

# --- GET: LISTAR USUÁRIOS ---
@router.get("", response_model=list[StaffUserResponse])
async def list_staff_users(
    restaurant_id: Optional[int] = Query(None, description="Filtrar por restaurante (Apenas Super Admin)"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    # require_admin(staff) # Opcional: verifique se essa função não barra o ID 1
    
    logged_user_rid = int(staff["restaurant_id"])
    is_super_admin = (logged_user_rid == 1) # Assumindo ID 1 = LetzIT

    target_rid = logged_user_rid 

    # Lógica de Permissão
    if is_super_admin:
        if restaurant_id:
            target_rid = restaurant_id
    else:
        if restaurant_id and restaurant_id != logged_user_rid:
            raise HTTPException(
                status_code=403, 
                detail="Você não tem permissão para visualizar a equipe de outros restaurantes."
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

# --- POST: CRIAR USUÁRIO ---
@router.post("", response_model=StaffUserResponse)    
async def create_staff_user(
    payload: StaffUserCreateRequest,
    # Adicionamos parametro para Super Admin criar user em outros restaurantes
    target_restaurant_id: Optional[int] = Query(None, description="ID do restaurante alvo (Apenas Super Admin)"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    require_admin(staff)
    
    logged_user_rid = int(staff["restaurant_id"])
    is_super_admin = (logged_user_rid == 1)
    
    # 1. Definição do Restaurante Alvo
    final_rid = logged_user_rid
    
    if is_super_admin:
        if target_restaurant_id:
            final_rid = target_restaurant_id
    else:
        # Se um admin comum tentar criar para outro, bloqueamos ou ignoramos
        if target_restaurant_id and target_restaurant_id != logged_user_rid:
             raise HTTPException(403, "Você só pode criar usuários para seu próprio restaurante.")

    # 2. Bloqueio de Hierarquia (Client Admin não cria Internal Admin)
    if not is_super_admin and payload.role == "INTERNAL_ADMIN":
        raise HTTPException(status_code=403, detail="Apenas a LetzIT pode criar novos Super Admins.")

    # 3. Geração de Token e Expiração (Faltava no seu snippet)
    token = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(hours=48) # Token vale 48h
    ph = None # Password hash começa nulo

    try:
        row = (await db.execute(
            text("""
              INSERT INTO restaurant_staff (
                  restaurant_id, email, password_hash, role, is_active, name,
                  activation_token, activation_expires_at, created_at
              )
              VALUES (:rid, :email, :ph, :role, false, :name, :tok, :exp, NOW())
              RETURNING id, restaurant_id, email, role, is_active, name, created_at, changed_at
             """),
            {
             "rid": final_rid,
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
        
        # Aqui entraria o envio de email em background task
        # print(f"Link de ativação: https://admin.letzit.com/activate?token={token}")
        
        return StaffUserResponse(**row)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Este e-mail já está cadastrado neste restaurante.")

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
    is_super_admin = (logged_user_rid == 1)

    # Proteção: Não deixar desativar a si mesmo
    my_staff_id = int(staff.get("id") or 0)
    if payload.is_active is False and staff_id == my_staff_id:
        raise HTTPException(status_code=400, detail="Você não pode desativar sua própria conta.")

    # Proteção: Client Admin não promove ninguém a Super Admin
    if not is_super_admin and payload.role == "INTERNAL_ADMIN":
        raise HTTPException(status_code=403, detail="Apenas a LetzIT pode definir Super Admins.")

    # MONTAGEM DA QUERY
    # Se for Client Admin, OBRIGAMOS o filtro restaurant_id = :rid
    # Se for Super Admin, permitimos alterar qualquer ID (removemos o filtro de restaurante)
    
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
        # Trava de segurança para admins normais
        sql += " AND restaurant_id = :rid"
        params["rid"] = logged_user_rid

    row = (await db.execute(text(sql + " RETURNING id, restaurant_id, email, role, is_active, name, created_at, changed_at"), params)).mappings().first()

    if not row:
        # Se não retornou nada, ou o ID não existe ou o Admin tentou mexer no staff de outro restaurante
        raise HTTPException(status_code=404, detail="Usuário não encontrado ou sem permissão.")

    await db.commit()
    return StaffUserResponse(**row)
