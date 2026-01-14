from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.security import hash_password

router = APIRouter(prefix="/staff/activation", tags=["staff-auth"])


class ActivationPreviewResponse(BaseModel):
    status: str  # OK
    email: EmailStr
    name: str | None = None


@router.get("/preview", response_model=ActivationPreviewResponse)
async def activation_preview(
    token: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> ActivationPreviewResponse:
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
        raise HTTPException(400, "Invalid activation token")
    if row["activation_expires_at"] is not None and row["activation_expires_at"] < now:
        raise HTTPException(400, "Activation token expired")
    if bool(row["is_active"]):
        raise HTTPException(409, "Account already activated")

    return ActivationPreviewResponse(status="OK", email=row["email"], name=row["name"])


class ActivationCompleteRequest(BaseModel):
    token: UUID
    password: str = Field(..., min_length=8, max_length=200)


class ActivationCompleteResponse(BaseModel):
    status: str  # ACTIVATED
    staff_id: int


@router.post("/complete", response_model=ActivationCompleteResponse)
async def activation_complete(
    payload: ActivationCompleteRequest,
    db: AsyncSession = Depends(get_db_session),
) -> ActivationCompleteResponse:
    now = datetime.now(timezone.utc)

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
        raise HTTPException(400, "Invalid activation token")
    if row["activation_expires_at"] is not None and row["activation_expires_at"] < now:
        raise HTTPException(400, "Activation token expired")
    if bool(row["is_active"]):
        raise HTTPException(409, "Account already activated")

    ph = hash_password(payload.password)

    await db.execute(
        text("""
            UPDATE restaurant_staff
            SET ph = :ph,
                is_active = true,
                activated_at = :now,
                activation_token = NULL,
                activation_expires_at = NULL
            WHERE id = :sid
        """),
        {"ph": ph, "now": now, "sid": int(row["id"])},
    )
    await db.commit()

    return ActivationCompleteResponse(status="ACTIVATED", staff_id=int(row["id"]))
