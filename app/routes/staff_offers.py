from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps import get_current_staff_user

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])

# --- SCHEMAS (Modelos de Dados) ---
# Centralizamos aqui para não espalhar código

class OfferCreate(BaseModel):
    title: str
    message: str # A mensagem personalizada ("Ei Osvaldo...")
    description: Optional[str] = None
    price_cents: int
    original_price_cents: Optional[int] = None
    
    # Regras de Negócio
    max_qty: Optional[int] = None # Estoque (ex: apenas 10 unidades)
    end_at: datetime
    
    # Segmentação (O "Smart Batch")
    radius_km: int = 5
    target_audience: str = "ALL" # ex: 'ALL', 'NEW_USERS', 'HIGH_SPENDERS'

class OfferUpdate(BaseModel):
    title: Optional[str] = None
    message: Optional[str] = None
    description: Optional[str] = None
    price_cents: Optional[int] = None
    max_qty: Optional[int] = None
    end_at: Optional[datetime] = None

class OfferResponse(BaseModel):
    id: int
    title: str
    status: str
    claimed_count: int
    max_qty: Optional[int]
    created_at: datetime
    end_at: datetime

# --- ENDPOINTS DE LEITURA (GET) ---

@router.get("/", response_model=List[OfferResponse])
async def list_offers(
    status: Optional[str] = "ACTIVE",
    limit: int = 50,
    current_staff: dict = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Lista as ofertas do restaurante logado.
    Pode filtrar por status (ACTIVE, ENDED, DRAFT).
    """
    rid = current_staff["restaurant_id"]
    
    # Monta a query
    sql = """
        SELECT id, title, status, claimed_count, max_qty, created_at, end_at
        FROM offers
        WHERE restaurant_id = :rid
    """
    params = {"rid": rid, "limit": limit}

    if status:
        sql += " AND status = :status"
        params["status"] = status
        
    sql += " ORDER BY created_at DESC LIMIT :limit"

    result = await db.execute(text(sql), params)
    return result.mappings().all()


@router.get("/audience-quote")
async def get_audience_quote(
    lat: float, 
    lon: float, 
    radius_km: int,
    db: AsyncSession = Depends(get_db_session),
    current_staff: dict = Depends(get_current_staff_user)
):
    """
    Calculadora de Audiência:
    Diz quantas pessoas existem no raio selecionado ANTES de criar a oferta.
    """
    radius_m = radius_km * 1000
    
    # Query PostGIS rápida para contar pontos dentro do raio
    query = text("""
        SELECT count(*) 
        FROM users 
        WHERE 
            geog IS NOT NULL 
            AND ST_DWithin(
                geog, 
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 
                :radius_m
            )
            AND is_blocked = FALSE
    """)
    
    count = (await db.execute(query, {
        "lon": lon, "lat": lat, "radius_m": radius_m
    })).scalar()
    
    return {
        "estimated_reach": count, 
        "radius_km": radius_km,
        "message": f"Você alcançará cerca de {count} pessoas nesta região."
    }

# --- ENDPOINTS DE ESCRITA (POST/PATCH/DELETE) ---

@router.post("/")
async def create_offer(
    offer: OfferCreate,
    current_staff: dict = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Cria uma nova oferta.
    """
    rid = current_staff["restaurant_id"]
    
    # 1. Validações básicas
    if offer.end_at < datetime.now(offer.end_at.tzinfo):
        raise HTTPException(400, "A data de término deve ser futura.")

    # 2. Insere no Banco
    query = text("""
        INSERT INTO offers (
            restaurant_id, title, message, description,
            price_cents, original_price_cents,
            max_qty, claimed_count,
            status, placement,
            created_at, end_at,
            radius_km, target_audience
        ) VALUES (
            :rid, :title, :msg, :desc,
            :price, :orig_price,
            :max_qty, 0,
            'ACTIVE', 'NORMAL',
            NOW(), :end_at,
            :radius, :audience
        )
        RETURNING id
    """)
    
    try:
        result = await db.execute(query, {
            "rid": rid,
            "title": offer.title,
            "msg": offer.message,
            "desc": offer.description,
            "price": offer.price_cents,
            "orig_price": offer.original_price_cents,
            "max_qty": offer.max_qty,
            "end_at": offer.end_at,
            "radius": offer.radius_km,
            "audience": offer.target_audience
        })
        new_id = result.scalar()
        await db.commit()
        
        return {"id": new_id, "status": "created", "message": "Oferta criada com sucesso!"}
        
    except Exception as e:
        await db.rollback()
        print(f"Erro ao criar oferta: {e}")
        raise HTTPException(500, "Erro interno ao salvar oferta.")


@router.patch("/{offer_id}")
async def update_offer(
    offer_id: int,
    payload: OfferUpdate,
    current_staff: dict = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Atualiza uma oferta existente (apenas campos permitidos).
    """
    rid = current_staff["restaurant_id"]
    
    # Verifica propriedade
    check = await db.execute(text("SELECT id FROM offers WHERE id=:oid AND restaurant_id=:rid"), {"oid": offer_id, "rid": rid})
    if not check.first():
        raise HTTPException(404, "Oferta não encontrada.")

    # Monta query dinâmica (só atualiza o que veio preenchido)
    fields = []
    params = {"oid": offer_id}
    
    if payload.title:
        fields.append("title = :title")
        params["title"] = payload.title
    if payload.max_qty:
        fields.append("max_qty = :max_qty")
        params["max_qty"] = payload.max_qty
    if payload.end_at:
        fields.append("end_at = :end_at")
        params["end_at"] = payload.end_at
        
    if not fields:
        return {"message": "Nada para atualizar"}
        
    query = text(f"UPDATE offers SET {', '.join(fields)} WHERE id = :oid")
    await db.execute(query, params)
    await db.commit()
    
    return {"status": "updated"}


@router.post("/{offer_id}/close")
async def close_offer(
    offer_id: int,
    current_staff: dict = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Encerra a oferta manualmente antes do prazo.
    """
    rid = current_staff["restaurant_id"]
    
    result = await db.execute(
        text("UPDATE offers SET status='ENDED', end_at=NOW() WHERE id=:oid AND restaurant_id=:rid returning id"),
        {"oid": offer_id, "rid": rid}
    )
    if not result.scalar():
        raise HTTPException(404, "Oferta não encontrada ou já encerrada.")
        
    await db.commit()
    return {"status": "closed", "message": "Oferta encerrada."}


@router.post("/{offer_id}/repeat")
async def repeat_offer(
    offer_id: int,
    current_staff: dict = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Função "Clonar": Cria uma cópia da oferta para reutilizar.
    Útil para promoções recorrentes.
    """
    rid = current_staff["restaurant_id"]
    
    # 1. Busca a original
    original = (await db.execute(
        text("SELECT * FROM offers WHERE id=:oid AND restaurant_id=:rid"),
        {"oid": offer_id, "rid": rid}
    )).mappings().first()
    
    if not original:
        raise HTTPException(404, "Oferta original não encontrada.")

    # 2. Calcula nova data (ex: +24 horas a partir de agora)
    new_end = datetime.now() + timedelta(hours=24) 
    # (Ou você pode manter a duração original, ex: end_at - created_at)

    # 3. Insere a cópia
    query = text("""
        INSERT INTO offers (
            restaurant_id, title, message, description,
            price_cents, original_price_cents,
            max_qty, claimed_count,
            status, placement,
            created_at, end_at,
            radius_km, target_audience
        ) VALUES (
            :rid, :title, :msg, :desc,
            :price, :orig_price,
            :max_qty, 0,
            'ACTIVE', :place,
            NOW(), :end,
            :rad, :aud
        ) RETURNING id
    """)
    
    new_id = (await db.execute(query, {
        "rid": rid,
        "title": original.title,
        "msg": original.message,
        "desc": original.description,
        "price": original.price_cents,
        "orig_price": original.original_price_cents,
        "max_qty": original.max_qty,
        "place": original.placement,
        "end": new_end,
        "rad": original.radius_km,
        "aud": original.target_audience
    })).scalar()
    
    await db.commit()
    return {"id": new_id, "status": "cloned", "message": "Oferta duplicada com sucesso!"}
