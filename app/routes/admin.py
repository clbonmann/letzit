from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr
from app.security import hash_password
from sqlalchemy.exc import IntegrityError

from app.db import get_db_session
from app.schemas.admin import (
    AddTargetsRequest,
    CreateOfferRequest,
    CreateOfferResponse,
    CreateRestaurantRequest,
    CreateRestaurantResponse,
    CreateUserRequest,
    CreateUserResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/users", response_model=CreateUserResponse)
async def create_user(
    payload: CreateUserRequest,
    db: AsyncSession = Depends(get_db_session),
) -> CreateUserResponse:
    # cria user
    row = (await db.execute(
        text("""
            INSERT INTO users (phone_e164, level, reputation, is_blocked)
            VALUES (:phone, :level, :rep, false)
            RETURNING id, phone_e164
        """),
        {"phone": payload.phone_e164, "level": payload.level, "rep": payload.reputation},
    )).mappings().first()

    # cria stats default
    await db.execute(
        text("""
            INSERT INTO user_stats (user_id, reviews_count, redeemed_count, no_show_count)
            VALUES (:uid, 0, 0, 0)
            ON CONFLICT (user_id) DO NOTHING
        """),
        {"uid": row["id"]},
    )

    await db.commit()
    return CreateUserResponse(id=row["id"], phone_e164=row["phone_e164"])


@router.post("/restaurants", response_model=CreateRestaurantResponse)
async def create_restaurant(
    payload: CreateRestaurantRequest,
    db: AsyncSession = Depends(get_db_session),
) -> CreateRestaurantResponse:
    row = (await db.execute(
        text("""
            INSERT INTO restaurants (name, cnpj, is_active)
            VALUES (:name, :cnpj, true)
            RETURNING id, name
        """),
        {"name": payload.name, "cnpj": payload.cnpj},
    )).mappings().first()

    await db.commit()
    return CreateRestaurantResponse(id=row["id"], name=row["name"])


@router.post("/offers", response_model=CreateOfferResponse)
async def create_offer(
    payload: CreateOfferRequest,
    db: AsyncSession = Depends(get_db_session),
) -> CreateOfferResponse:
    # valida restaurant
    r = (await db.execute(
        text("SELECT id FROM restaurants WHERE id = :rid AND is_active = true"),
        {"rid": payload.restaurant_id},
    )).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found/active")

    row = (await db.execute(
        text("""
            INSERT INTO offers (
              restaurant_id, title, description, end_at,
              status, accept_limit, accepted_count,
              target_batch_size, max_target_total, released_total,
              accept_ttl_hours, cancel_grace_min
            )
            VALUES (
              :rid, :title, :desc, :end_at,
              'ACTIVE', :accept_limit, 0,
              :batch_size, :max_total, 0,
              :ttl_hours, 0
            )
            RETURNING id, status, accept_limit, end_at
        """),
        {
            "rid": payload.restaurant_id,
            "title": payload.title,
            "desc": payload.description,
            "end_at": payload.end_at,
            "accept_limit": payload.accept_limit,
            "batch_size": payload.target_batch_size,
            "max_total": payload.max_target_total,
            "ttl_hours": payload.accept_ttl_hours,
        },
    )).mappings().first()

    await db.commit()
    return CreateOfferResponse(
        id=row["id"],
        status=row["status"],
        accept_limit=row["accept_limit"],
        end_at=row["end_at"],
    )


@router.post("/offers/{offer_id}/targets")
async def add_targets(
    offer_id: int, 
    payload: AddTargetsRequest, 
    db: AsyncSession = Depends(get_db_session)
) -> dict:
    # 1. Validação rápida
    offer_exists = (await db.execute(text("SELECT 1 FROM offers WHERE id = :oid"), {"oid": offer_id})).scalar()
    if not offer_exists:
        raise HTTPException(status_code=404, detail="Offer not found")

    # 2. Bulk Insert usando UNNEST (Magia do Postgres)
    # Inserimos tudo de uma vez, ignorando duplicatas (ON CONFLICT DO NOTHING)
    # E retornamos quem foi inserido de fato.
    result = await db.execute(
        text("""
            INSERT INTO offer_targets (offer_id, user_id, batch_no, state, released_at)
            SELECT :oid, u.id, :batch, :state, now()
            FROM users u
            WHERE u.id = ANY(:user_ids)
            ON CONFLICT (offer_id, user_id) DO NOTHING
            RETURNING user_id
        """),
        {
            "oid": offer_id,
            "user_ids": payload.user_ids, # Passamos o array direto pro Postgres
            "batch": payload.batch_no,
            "state": payload.state
        }
    )
    inserted_ids = result.scalars().all()
    
    # 3. Atualiza o status da oferta se necessário (Atômico)
    if inserted_ids:
        await db.execute(
            text("""
               UPDATE offers SET status = 'ACTIVE' 
               WHERE id = :oid AND status = 'CREATED'
            """),
            {"oid": offer_id}
        )
    
    await db.commit()

    return {
        "ok": True,
        "offer_id": offer_id,
        "targets_added": len(inserted_ids),
        "requested_count": len(payload.user_ids)
    }
    
class CreateStaffRequest(BaseModel):
    restaurant_id: int
    email: EmailStr
    password: str
    role: str = "admin"  # admin | cashier

@router.post("/staff")
async def create_staff(
    payload: CreateStaffRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    role = payload.role.strip().lower()
    if role not in {"INTERNAL_ADMIN", "CLIENT_ADMIN", "CLIENT_STAFF"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="role must be INTERNAL_ADMIN, CLIENT_ADMIN or CLIENT_STAFF")

    # valida restaurant
    r = (await db.execute(
        text("SELECT id FROM restaurants WHERE id = :rid AND is_active = true"),
        {"rid": payload.restaurant_id},
    )).first()
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found/active")

    try:
        row = (await db.execute(
            text("""
                INSERT INTO restaurant_staff (restaurant_id, email, password_hash, role, is_active)
                VALUES (:rid, :email, :ph, :role, true)
                RETURNING id, restaurant_id, email, role
            """),
            {
                "rid": payload.restaurant_id,
                "email": payload.email.strip().lower(),
                "ph": hash_password(payload.password),
                "role": role,
            },
        )).mappings().first()

        await db.commit()

    except IntegrityError as e:
        await db.rollback()
        msg = str(e.orig).lower() if getattr(e, "orig", None) else str(e).lower()

        # email duplicado no mesmo restaurante (uq_restaurant_email)
        if "uq_restaurant_email" in msg or "unique" in msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Staff email already exists for this restaurant")

        # check role (ck_restaurant_staff_role)
        if "ck_restaurant_staff_role" in msg or "check constraint" in msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

        # fallback
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid data")

    return {
        "id": int(row["id"]),
        "restaurant_id": int(row["restaurant_id"]),
        "email": row["email"],
        "role": row["role"],
    }

