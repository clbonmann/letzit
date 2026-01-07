from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
            INSERT INTO restaurants (name, is_active)
            VALUES (:name, true)
            RETURNING id, name
        """),
        {"name": payload.name},
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
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    # valida offer
    offer = (await db.execute(
        text("SELECT id FROM offers WHERE id = :oid"),
        {"oid": offer_id},
    )).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    # insere targets (idempotente)
    inserted = 0
    for uid in payload.user_ids:
        res = await db.execute(
            text("""
                INSERT INTO offer_targets (offer_id, user_id, batch_no, state)
                VALUES (:oid, :uid, :batch, :state)
                ON CONFLICT (offer_id, user_id) DO NOTHING
            """),
            {"oid": offer_id, "uid": uid, "batch": payload.batch_no, "state": payload.state},
        )
        # rowcount pode ser None dependendo do driver; então contamos via SELECT depois (simples)
        inserted += 1

    await db.commit()

    count_targets = (await db.execute(
        text("SELECT COUNT(*) AS c FROM offer_targets WHERE offer_id = :oid"),
        {"oid": offer_id},
    )).mappings().first()["c"]

    return {"ok": True, "offer_id": offer_id, "targets_total": int(count_targets)}
