from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.perms_staff import require_admin
from app.security import hash_password

router = APIRouter(prefix="/staff/users", tags=["staff-users"])


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=200)


class ResetPasswordResponse(BaseModel):
    staff_id: int
    status: str  # "OK"


@router.post("/{staff_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_staff_password(
    staff_id: int,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> ResetPasswordResponse:
    require_admin(staff)

    rid = int(staff["restaurant_id"])
    actor_role = str(staff.get("role") or "")
    actor_staff_id = int(staff.get("staff_id") or staff.get("id") or 0)

    # busca alvo (tem que ser do mesmo restaurante)
    target = (await db.execute(
        text("""
            SELECT id, role, is_active
            FROM restaurant_staff
            WHERE id = :sid AND restaurant_id = :rid
        """),
        {"sid": int(staff_id), "rid": rid},
    )).mappings().first()

    if not target:
        raise HTTPException(status_code=404, detail="Staff user not found")

    if not bool(target["is_active"]):
        raise HTTPException(status_code=409, detail="Target staff user is inactive")

    target_role = str(target["role"] or "")

    # CLIENT_ADMIN não pode mexer em INTERNAL_ADMIN
    if actor_role != "INTERNAL_ADMIN" and target_role == "INTERNAL_ADMIN":
        raise HTTPException(status_code=403, detail="Only INTERNAL_ADMIN can reset INTERNAL_ADMIN password")

    # (Opcional) se quiser bloquear reset da própria senha aqui:
    # if int(staff_id) == actor_staff_id:
    #     raise HTTPException(status_code=400, detail="Use /staff/change-password to change your own password")

    new_hash = hash_password(payload.new_password)

    await db.execute(
        text("""
            UPDATE restaurant_staff
            SET ph = :ph
            WHERE id = :sid AND restaurant_id = :rid
        """),
        {"ph": new_hash, "sid": int(staff_id), "rid": rid},
    )
    await db.commit()

    return ResetPasswordResponse(staff_id=int(staff_id), status="OK")
