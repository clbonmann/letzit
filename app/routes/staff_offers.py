from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import traceback
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import insert, text, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.functions import ST_DWithin
from enum import Enum

# Imports do App
from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.constants.pricing import PRICE_PER_KM_ADHOC
from app.constants.offer_types import OFFER_TYPE_METADATA
from app.services.storage import upload_image  # Certifique-se que esta função existe no seu projeto

# Models e Schemas
from app.models import Offer, OfferTarget, Restaurant, Client, OfferType
from app.schemas.staff import (
    QuoteRequest, QuoteResponse, CreateOfferRequest, CreateOfferResponse,
    CloseOfferResponse
)

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])

# --- FUNÇÕES AUXILIARES ---
def _staff_id(staff: dict) -> int: return int(staff.get("id") or staff.get("id"))
def _utc_day_window(now: datetime) -> tuple: return datetime(now.year, now.month, now.day, tzinfo=timezone.utc), datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)

# --- ENDPOINT 0: UPLOAD DE IMAGENS (NOVO) ---
# app/routes/staff_offers.py

@router.post("/offer-images")
async def upload_offer_image(
    files: List[UploadFile] = File(...), 
    staff: dict = Depends(get_current_staff)
):
    restaurant_id = int(staff["restaurant_id"])
    new_urls = []

    # Configuração do Cloudinary
    transformations = {
        "width": 600, 
        "height": 400, 
        "crop": "fill", 
        "gravity": "center",
        "fetch_format": "auto"
    }

    try:
        for file in files:
            # Garante que o ponteiro de leitura está no início
            await file.seek(0)
            
            # --- CORREÇÃO AQUI ---
            # Passamos o 'file' (UploadFile) direto, e não 'file.file'.
            # Sua função upload_image deve saber lidar com o wrapper do FastAPI.
            url = upload_image(
                file, 
                folder=f"restaurants/{restaurant_id}/offers/",
                transformation=transformations 
            )
            
            new_urls.append(url)
            
    except Exception as e:
        print(f"Upload Error: {e}")
        # Dica: Se der erro de novo, verifique o arquivo app/services/storage.py
        raise HTTPException(500, f"Falha no upload: {str(e)}")

    return {"urls": new_urls}

# --- ENDPOINT 1: LISTAR (AGORA HÍBRIDO: LISTA OU DETALHE) ---
@router.get("", summary="List or Get Offer")
async def list_staff_offers(
    offer_id: int | None = Query(None, description="Se enviado, filtra por esta oferta específica"),
    status: str | None = Query(None), 
    placement: str | None = Query(None), 
    limit: int = Query(50), 
    db: AsyncSession = Depends(get_db_session), 
    staff: dict = Depends(get_current_staff)
    ):
    """
    Lista ofertas. Se 'offer_id' for informado, retorna apenas aquela oferta.
    """
    # Query completa com todos os campos necessários
    sql = """
        SELECT 
            o.id, 
            o.title, 
            o.message, 
            o.offer_image_url,  -- <--- NOVO CAMPO
            o.placement, 
            o.radius_km, 
            o.price_cents,
            o.original_price_cents, 
            o.status, 
            o.accept_limit, 
            o.accepted_count, 
            o.created_at, 
            o.end_at,
            o.offer_type,        
            o.audience_estimate, 
            o.offer_image_url,
            COUNT(c.id) FILTER (WHERE c.status='REDEEMED')::int AS redeemed_count, 
            COUNT(c.id) FILTER (WHERE c.status='NO_SHOW')::int AS no_show_count 
        FROM offers o 
        LEFT JOIN offer_claims c ON c.offer_id = o.id 
        WHERE o.restaurant_id = :rid
    """
    
    params = {"rid": int(staff["restaurant_id"]), "limit": limit}
    
    # --- FILTROS DINÂMICOS ---
    
    # 1. Filtro por ID (Prioridade para detalhes/repeat)
    if offer_id:
        sql += " AND o.id = :oid"
        params["oid"] = offer_id
    
    # 2. Outros filtros (só aplicam se não for busca por ID específico, ou cumulativo)
    if status: 
        sql += " AND o.status = :status"
        params["status"] = status
    if placement: 
        sql += " AND o.placement = :placement"
        params["placement"] = placement
        
    sql += " GROUP BY o.id ORDER BY o.created_at DESC LIMIT :limit"
    
    result = (await db.execute(text(sql), params)).mappings().all()
    
    return result

# --- ENDPOINT 2: COTAÇÃO ---
@router.post("/quote", response_model=QuoteResponse)
async def quote_offer(
    payload: QuoteRequest, 
    db: AsyncSession = Depends(get_db_session), 
    staff: dict = Depends(get_current_staff)
):
    rid = int(staff["restaurant_id"])

    # 1. Buscar Restaurante (Geo + Saldo de KM)
    stmt_rest = select(Restaurant).where(Restaurant.id == rid)
    result_rest = await db.execute(stmt_rest)
    rest = result_rest.scalar_one_or_none()

    if not rest or not rest.geog:
        raise HTTPException(400, "Localização do restaurante inválida.")

    # PLACEMENT "NORMAL"
    if payload.placement == "NORMAL":
        if not payload.radius_km:
            raise HTTPException(400, "radius_km é obrigatório para placement NORMAL.")

        radius_km = int(payload.radius_km)
        radius_meters = radius_km * 1000
        
        # Calcular Audiência
        stmt_aud = select(func.count(Client.id)).where(
            ST_DWithin(Client.geog, rest.geog, radius_meters)
        )
        aud_result = await db.execute(stmt_aud)
        audience = aud_result.scalar() or 0

        # Calcular Preço
        price_cents = 0
        quote_msg = ""

        if rest.balance_km >= radius_km:
            price_cents = 0
            quote_msg = f"Coberto pelo seu pacote (Saldo atual: {rest.balance_km}km)"
        else:
            price_amount = radius_km * PRICE_PER_KM_ADHOC
            price_cents = int(price_amount * 100)
            quote_msg = f"Preço avulso por Km (Sem pacote ativo)"

        return QuoteResponse(
            placement="NORMAL",
            radius_km=radius_km,
            price_cents=price_cents,
            wallet_balance_km=rest.balance_km,
            audience_estimate=audience,
            message=quote_msg
        )

    # PLACEMENT "CITY_HOME"
    if payload.placement == "CITY_HOME":
        fixed_radius = 20
        fixed_price = 5000 
        
        stmt_aud = select(func.count(Client.id)).where(
            ST_DWithin(Client.geog, rest.geog, fixed_radius * 1000)
        )
        audience = (await db.execute(stmt_aud)).scalar() or 0

        return QuoteResponse(
            placement="CITY_HOME",
            radius_km=fixed_radius,
            price_cents=fixed_price,
            wallet_balance_km=rest.balance_km,
            audience_estimate=audience,
            status="AVAILABLE",
            message="Destaque na Home da Cidade"
        )

    raise HTTPException(400, "Invalid placement type")

# --- ENDPOINT 3: CRIAR ---
@router.post("", response_model=CreateOfferResponse)
async def create_offer(
    payload: CreateOfferRequest, 
    db: AsyncSession = Depends(get_db_session), 
    staff: dict = Depends(get_current_staff)
):
    rid = int(staff["restaurant_id"])
    staff_id = int(staff["id"])
    now = datetime.now(timezone.utc)

    # --- 1. CÁLCULO DAS DATAS ---
    start_time = payload.start_at if payload.start_at else now

    if payload.end_at:
        end_time = payload.end_at
    elif payload.active_minutes:
        end_time = start_time + timedelta(minutes=payload.active_minutes)
    else:
        raise HTTPException(status_code=400, detail="Você deve informar 'end_at' ou 'active_minutes'.")

    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="A data de término deve ser posterior à data de início.")

    # --- 2. Busca Geolocation ---
    stmt_rest = select(Restaurant.geog).where(Restaurant.id == rid)
    result_rest = await db.execute(stmt_rest)
    restaurant_geog = result_rest.scalar_one_or_none()

    if not restaurant_geog:
        raise HTTPException(400, "Restaurante sem localização cadastrada.")

    # --- 3. Calcular Audiência ---
    radius_meters = (payload.radius_km or 25) * 1000
    stmt_count = select(func.count(Client.id)).where(
        ST_DWithin(Client.geog, restaurant_geog, radius_meters)
    )
    result_count = await db.execute(stmt_count)
    audience_estimate = result_count.scalar() or 0

    # --- 4. Criar Objeto ---
    initial_status = "CREATED" if start_time <= now else "SCHEDULED"
    
    offer_type_val = payload.offer_type.value if hasattr(payload.offer_type, 'value') else payload.offer_type

    # Nota: payload.offer_image_url deve vir do Schema CreateOfferRequest
    new_offer = Offer(
        restaurant_id=rid,
        staff_id=staff_id,
        title=payload.title,
        description=payload.message,
        offer_image_url=payload.offer_image_url, # <--- NOVO CAMPO
        start_at=start_time,
        end_at=end_time,
        offer_type=offer_type_val,
        status=initial_status,
        radius_km=payload.radius_km,
        placement=payload.placement,
        price_cents=payload.price_cents or 0,
        original_price_cents=payload.original_price_cents or 0,
        accept_limit=payload.accept_limit,
        max_target_total=payload.max_target_total,
        audience_estimate=audience_estimate,
        created_at=now,
        updated_at=now,
        geog=restaurant_geog
    )

    db.add(new_offer)
    await db.commit()
    await db.refresh(new_offer)

    return CreateOfferResponse(
        offer_id=new_offer.id,
        staff_id=new_offer.staff_id,
        placement=new_offer.placement,
        radius_km=new_offer.radius_km,
        price_cents=new_offer.price_cents,
        original_price_cents=new_offer.original_price_cents,
        title=new_offer.title,
        message=new_offer.description,
        accept_limit=new_offer.accept_limit,
        max_target_total=new_offer.max_target_total,
        status=new_offer.status,
        start_at=new_offer.start_at,
        end_at=new_offer.end_at,
        audience_estimate=new_offer.audience_estimate
    )

# --- ENDPOINT 4: FECHAR ---
@router.patch("/{offer_id}/close", response_model=CloseOfferResponse)
async def close_offer(
    offer_id: int, 
    db: AsyncSession = Depends(get_db_session), 
    staff: dict = Depends(get_current_staff)
):
    stmt = select(Offer).where(
        Offer.id == offer_id,
        Offer.restaurant_id == int(staff["restaurant_id"])
    )
    result = await db.execute(stmt)
    offer_obj = result.scalar_one_or_none()

    if not offer_obj:
        raise HTTPException(404, "Oferta não encontrada ou não pertence ao seu restaurante.")

    if offer_obj.status in ["CLOSED", "EXPIRED"]:
        raise HTTPException(400, "Oferta já fechada ou expirada.")
    
    offer_obj.status = "CLOSED"
    offer_obj.status_reason = "MANUAL_CLOSE"
    offer_obj.closed_at = datetime.now(timezone.utc)
    offer_obj.status_changed_by_staff_id = int(staff["id"])

    await db.commit()
    await db.refresh(offer_obj)

    return CloseOfferResponse(
        offer_id=offer_obj.id,
        previous_status=offer_obj.status,
        status=offer_obj.status,
        status_reason=offer_obj.status_reason,
        closed_at=offer_obj.closed_at
    )

# --- ENDPOINT 5: TIPOS ---
@router.get("/types")
async def get_offer_types(staff: dict = Depends(get_current_staff)):
    response = []
    for type_enum in OfferType:
        meta = OFFER_TYPE_METADATA.get(type_enum.value, {"label": type_enum.value, "description": "Oferta especial", "icon": "🏷️"})
        response.append({
            "value": type_enum.value,
            "label": meta["label"],
            "description": meta["description"],
            "icon": meta["icon"]
        })
    return response

# --- ENDPOINT 6: PUBLICAR ---
@router.post("/{offer_id}/publish", response_model=CreateOfferResponse)
async def publish_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    stmt = select(Offer).where(
        Offer.id == offer_id,
        Offer.restaurant_id == int(staff["restaurant_id"])
    )
    result = await db.execute(stmt)
    offer = result.scalar_one_or_none()

    if not offer:
        raise HTTPException(404, "Oferta não encontrada.")
    
    if offer.status != "CREATED":
        raise HTTPException(400, "Apenas ofertas com status 'CREATED' podem ser publicadas.")

    stmt_rest = select(Restaurant).where(Restaurant.id == offer.restaurant_id)
    res_rest = await db.execute(stmt_rest)
    restaurant = res_rest.scalar_one_or_none()

    if not restaurant:
        raise HTTPException(404, "Restaurante não encontrado.")

    # COBRANÇA
    radius_needed = int(offer.radius_km or 20)
    cost_in_money = 0.0
    payment_method = "CREDITS"

    if restaurant.balance_km >= radius_needed:
        restaurant.balance_km -= radius_needed
        payment_method = "CREDITS"
        cost_in_money = 0.0
    else:
        payment_method = "PAY_AS_YOU_GO"
        cost_in_money = radius_needed * PRICE_PER_KM_ADHOC

    offer.payment_method = payment_method
    offer.cost_amount = cost_in_money

    # ATUALIZAR STATUS
    now = datetime.now(timezone.utc)
    new_status = "ACTIVE" if offer.start_at <= now else "SCHEDULED"
    offer.status = new_status
    offer.start_at = now 
    offer.updated_at = now
    await db.commit()
    await db.refresh(offer)

    return CreateOfferResponse(
        offer_id=offer.id,
        staff_id=int(staff["id"]), 
        offer_type=offer.offer_type,
        placement=offer.placement,
        radius_km=offer.radius_km,
        price_cents=int(offer.cost_amount * 100), 
        audience_estimate=offer.audience_estimate,
        status=offer.status,
        start_at=offer.start_at,
        end_at=offer.end_at
    )

@router.get("/audience-estimation")
async def get_audience_estimation(
    radius_km: float = Query(..., ge=0.1, le=50), # Validação básica (min 100m, max 50km)
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Calcula quantos usuários estão dentro do raio especificado a partir do restaurante.
    """
    rid = int(staff.get("restaurant_id") or 0)

    # 1. Buscar localização do Restaurante
    stmt_rest = select(Restaurant.geog).where(Restaurant.id == rid)
    result_rest = await db.execute(stmt_rest)
    restaurant_geog = result_rest.scalars().first()

    if not restaurant_geog:
        # Se o restaurante não tem lat/long configurado, a estimativa é 0
        return {"estimated_audience": 0, "radius_km": radius_km}

    # 2. Converter Km para Metros (PostGIS usa metros para Geography)
    radius_meters = radius_km * 1000

    # 3. Contar Usuários na área (Query Espacial)
    stmt_count = select(func.count(Client.id)).where(
        ST_DWithin(Client.geog, restaurant_geog, radius_meters)
    )
    
    result_count = await db.execute(stmt_count)
    count = result_count.scalar() or 0

    return {
        "estimated_audience": count,
        "radius_km": radius_km,
        "center_point": "Restaurante"
    }