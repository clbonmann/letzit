from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
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
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    require_admin(staff)
    rid = int(staff["restaurant_id"])

    rows = (await db.execute(
        text("""
            SELECT id, restaurant_id, email, role, is_active, name, created_at, changed_at
            FROM restaurant_staff
            WHERE restaurant_id = :rid
            ORDER BY created_at DESC
        """),
        {"rid": rid},
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

    ph = hash_password(payload.password)

    try:
        row = (await db.execute(
            text("""
                INSERT INTO restaurant_staff (restaurant_id, email, ph, role, is_active, name)
                VALUES (:rid, :email, :ph, :role, true, :name)
                RETURNING id, restaurant_id, email, role, is_active, name, created_at, changed_at
            """),
            {
                "rid": rid,
                "email": str(payload.email).lower(),
                "ph": ph,
                "role": payload.role,
                "name": payload.name,
            },
        )).mappings().first()

        await db.commit()
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
