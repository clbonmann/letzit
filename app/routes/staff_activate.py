from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.db import get_db_session

router = APIRouter(prefix="/staff", tags=["staff-auth"])


class ActivateResponse(BaseModel):
    status: str  # "ACTIVATED"
    staff_id: int


@router.get("/activate", response_model=ActivateResponse)
async def activate_staff(
    token: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> ActivateResponse:
    now = datetime.now(timezone.utc)

    row = (await db.execute(
        text("""
            SELECT id, is_active, activation_expires_at
            FROM restaurant_staff
            WHERE activation_token = :tok
            FOR UPDATE
        """),
        {"tok": str(token)},
    )).mappings().first()

    if not row:
        raise HTTPException(400, "Invalid activation token")

    if row["activation_expires_at"] is not None and row["activation_expires_at"] < now:
        raise HTTPException(400, "Activation token expired")

    if bool(row["is_active"]):
        # já ativado: idempotente
        return ActivateResponse(status="ACTIVATED", staff_id=int(row["id"]))

    await db.execute(
        text("""
            UPDATE restaurant_staff
            SET is_active = true,
                activated_at = :now,
                activation_token = NULL,
                activation_expires_at = NULL
            WHERE id = :sid
        """),
        {"sid": int(row["id"]), "now": now},
    )
    await db.commit()

    return ActivateResponse(status="ACTIVATED", staff_id=int(row["id"]))
