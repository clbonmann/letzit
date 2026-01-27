from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.emails.staff_invite import build_staff_invite_email
from app.security import get_password_hash
from app.db import get_db_session
# IMPORTANDO SCHEMAS
from app.schemas.admin import (
    AddTargetsRequest, CreateOfferRequest, CreateOfferResponse,
    CreateRestaurantRequest, CreateRestaurantResponse,
    CreateClientRequest, CreateClientResponse, CreateStaffRequest
)
from app.services.email import send_invite_email

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/clients", response_model=CreateClientResponse)
async def create_client(payload: CreateClientRequest, db: AsyncSession = Depends(get_db_session)):
    row = (await db.execute(text("INSERT INTO clients (phone_e164, level, reputation, is_blocked) VALUES (:phone, :level, :rep, false) RETURNING id, phone_e164"), {"phone": payload.phone_e164, "level": payload.level, "rep": payload.reputation})).mappings().first()
    await db.execute(text("INSERT INTO client_stats (client_id, reviews_count, redeemed_count, no_show_count) VALUES (:uid, 0, 0, 0) ON CONFLICT (client_id) DO NOTHING"), {"uid": row.id})
    await db.commit()
    return CreateClientResponse(id=row.id, phone_e164=row.phone_e164)

@router.post("/restaurants", response_model=CreateRestaurantResponse)
async def create_restaurant(
    payload: CreateRestaurantRequest, 
    db: AsyncSession = Depends(get_db_session)
):
    # 1. CRIAR RESTAURANTE
    # Inserimos e retornamos o ID imediatamente
    query_rest = text("""
        INSERT INTO restaurants (name, cnpj, is_active) 
        VALUES (:name, :cnpj, true) 
        RETURNING id, name
    """)
    row_rest = (await db.execute(query_rest, {"name": payload.name, "cnpj": payload.cnpj})).mappings().first()
    
    restaurant_id = row_rest.id
    restaurant_name = row_rest.name
    # 2. GERAR TOKEN DE CONVITE (UUID)
    invite_token = str(uuid.uuid4())

    # 3. CRIAR USUÁRIO ADMIN (Status PENDING ou similar)
    # Importante: Salvamos o invite_token no banco para validar depois quando ele clicar no link
    # Supondo que sua tabela 'staff' ou 'users' tenha um campo 'invite_token' e 'status'
    query_user = text("""
        INSERT INTO restaurant_staff (restaurant_id, name, email, role, is_active, activation_token)
        VALUES (:rest_id, :name, :email, :role, false, :token)
    """)
    
    await db.execute(query_user, {
        "rest_id": restaurant_id,
        "name": payload.admin_name,
        "email": payload.admin_email,
        "role": payload.role,
        "token": invite_token
    })

    # 4. COMMITAR A TRANSAÇÃO (Salvar tudo)
    await db.commit()

    # 5. ENVIAR O EMAIL (Background Task é melhor, mas await direto funciona pra testar)
    # Chamamos a função que você já criou
    await send_invite_email(payload.admin_name, restaurant_name, payload.admin_email, invite_token)

    return CreateRestaurantResponse(id=restaurant_id, name=restaurant_name)
