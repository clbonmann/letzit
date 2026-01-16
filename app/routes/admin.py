from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.security import get_password_hash
from app.db import get_db_session
# IMPORTANDO SCHEMAS
from app.schemas.admin import (
    AddTargetsRequest, CreateOfferRequest, CreateOfferResponse,
    CreateRestaurantRequest, CreateRestaurantResponse,
    CreateClientRequest, CreateClientResponse, CreateStaffRequest
)

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/clients", response_model=CreateClientResponse)
async def create_client(payload: CreateClientRequest, db: AsyncSession = Depends(get_db_session)):
    row = (await db.execute(text("INSERT INTO clients (phone_e164, level, reputation, is_blocked) VALUES (:phone, :level, :rep, false) RETURNING id, phone_e164"), {"phone": payload.phone_e164, "level": payload.level, "rep": payload.reputation})).mappings().first()
    await db.execute(text("INSERT INTO client_stats (client_id, reviews_count, redeemed_count, no_show_count) VALUES (:uid, 0, 0, 0) ON CONFLICT (client_id) DO NOTHING"), {"uid": row.id})
    await db.commit()
    return CreateClientResponse(id=row.id, phone_e164=row.phone_e164)

@router.post("/restaurants", response_model=CreateRestaurantResponse)
async def create_restaurant(payload: CreateRestaurantRequest, db: AsyncSession = Depends(get_db_session)):
    row = (await db.execute(text("INSERT INTO restaurants (name, cnpj, is_active) VALUES (:name, :cnpj, true) RETURNING id, name"), {"name": payload.name, "cnpj": payload.cnpj})).mappings().first()
    await db.commit()
    return CreateRestaurantResponse(id=row.id, name=row.name)

# ... (Repita o padrão para create_offer e add_targets usando os schemas importados)
