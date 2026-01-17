from __future__ import annotations
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import insert, text, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from geoalchemy2.functions import ST_DWithin
from enum import Enum
from app.constants.pricing import PRICE_PER_KM_ADHOC
from app.constants.offer_types import OFFER_TYPE_METADATA

from fastapi import APIRouter, Depends
from app.models import OfferType

from app.db import get_db_session
from app.deps_staff import get_current_staff
# IMPORTANDO SCHEMAS
from app.models import Offer, OfferTarget, Restaurant, Client, OfferType
from app.schemas.staff import (
    QuoteRequest, QuoteResponse, CreateOfferRequest, CreateOfferResponse,
    UpdateCreatedOfferRequest, UpdateCreatedOfferResponse,
    CloseOfferRequest, CloseOfferResponse, RepeatOfferRequest, RepeatOfferResponse
)

router = APIRouter(prefix="/staff/offers", tags=["staff-offers"])

def _staff_id(staff: dict) -> int: return int(staff.get("id") or staff.get("id"))
def _normalize_city(s: str) -> str: return s.strip().lower().replace(" ", "_").replace("-", "_")
def _utc_day_window(now: datetime) -> tuple: return datetime(now.year, now.month, now.day, tzinfo=timezone.utc), datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)

@router.get("", summary="List Offers")
async def list_staff_offers(
    status: str | None = Query(None), 
    placement: str | None = Query(None), 
    limit: int = Query(50), 
    db: AsyncSession = Depends(get_db_session), 
    staff: dict = Depends(get_current_staff)
    ):
    sql = "SELECT o.id, o.title, o.message, o.placement, o.radius_km, o.price_cents, o.status, o.accept_limit, o.accepted_count, " \
    "o.created_at, o.end_at, COUNT(c.id) FILTER (WHERE c.status='REDEEMED')::int AS redeemed_count, COUNT(c.id) " \
    "FILTER (WHERE c.status='NO_SHOW')::int AS no_show_count FROM offers o LEFT JOIN offer_claims c ON c.offer_id = o.id WHERE o.restaurant_id = :rid"
    params = {"rid": int(staff["restaurant_id"]), "limit": limit}
    if status: sql += " AND o.status = :status"; params["status"] = status
    if placement: sql += " AND o.placement = :placement"; params["placement"] = placement
    sql += " GROUP BY o.id ORDER BY o.created_at DESC LIMIT :limit"
    return (await db.execute(text(sql), params)).mappings().all()

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

    # ==================================================================
    # LÓGICA 1: PLACEMENT "NORMAL" (Baseado no Raio e Saldo de KM)
    # ==================================================================
    if payload.placement == "NORMAL":
        if not payload.radius_km:
            raise HTTPException(400, "radius_km é obrigatório para placement NORMAL.")

        radius_km = int(payload.radius_km)
        radius_meters = radius_km * 1000
        # A. Calcular Audiência (PostGIS)
        # Contamos quantos clientes estão no raio
        stmt_aud = select(func.count(Client.id)).where(
            ST_DWithin(Client.geog, rest.geog, radius_meters)
        )
        # Opcional: Se tiver campo last_loc_at, descomente abaixo:
        # stmt_aud = stmt_aud.where(Client.last_loc_at > datetime.now() - timedelta(minutes=payload.active_minutes))
        
        aud_result = await db.execute(stmt_aud)
        audience = aud_result.scalar() or 0

        # B. Calcular Preço (A lógica do KM Wallet)
        price_cents = 0
        quote_msg = ""

        if rest.balance_km >= radius_km:
            # Tem saldo suficiente no pacote
            price_cents = 0
            quote_msg = f"Coberto pelo seu pacote (Saldo atual: {rest.balance_km}km)"
        else:
            # Não tem saldo, paga avulso
            price_amount = radius_km * PRICE_PER_KM_ADHOC
            price_cents = int(price_amount * 100)
            quote_msg = f"Preço avulso por Km (Sem pacote ativo)"

        return QuoteResponse(
            placement="NORMAL",
            radius_km=radius_km,
            price_cents=price_cents,
            wallet_balance_km=rest.balance_km,
            audience_estimate=audience,
            message=quote_msg # Campo novo opcional no response para feedback
        )

    # ==================================================================
    # LÓGICA 2: PLACEMENT "CITY_HOME" (Slots Premium)
    # OBS: Essa lógica requer tabelas 'city_offers_pricing' e 'city_offer_slots'
    # Vou manter a estrutura preparada para quando criarmos essas tabelas.
    # ==================================================================
    if payload.placement == "CITY_HOME":
        # Simulação temporária até criarmos as tabelas de City Slots
        # Supondo preço fixo de R$ 50,00 para aparecer na Home da Cidade
        
        fixed_radius = 20
        fixed_price = 5000 # 50 reais em centavos
        
        # Audiência da cidade inteira (20km)
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
            city=rest.city or "Unknown",
            status="AVAILABLE", # Mockado por enquanto
            message="Destaque na Home da Cidade"
        )

    raise HTTPException(400, "Invalid placement type")

@router.post("", response_model=CreateOfferResponse)
async def create_offer(
    payload: CreateOfferRequest, 
    db: AsyncSession = Depends(get_db_session), 
    staff: dict = Depends(get_current_staff)
):
    rid = int(staff["restaurant_id"])
    staff_id = int(staff["id"])
    now = datetime.now(timezone.utc)

    # --- 1. CÁLCULO DAS DATAS (Resolvemos os Nones aqui) ---
    
    # Se start_at for None, assumimos "Agora"
    start_time = payload.start_at if payload.start_at else now

    # Se end_at for None, calculamos via active_minutes
    if payload.end_at:
        end_time = payload.end_at
    elif payload.active_minutes:
        end_time = start_time + timedelta(minutes=payload.active_minutes)
    else:
        raise HTTPException(status_code=400, detail="Você deve informar 'end_at' ou 'active_minutes'.")

    # --- 2. VALIDAÇÃO (Agora segura, pois as variáveis têm datas reais) ---
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="A data de término deve ser posterior à data de início.")

    # --- 3. Restante da Lógica (Geo, Audiência, etc...) ---
    
    # Buscar Geolocation
    stmt_rest = select(Restaurant.geog).where(Restaurant.id == rid)
    result_rest = await db.execute(stmt_rest)
    restaurant_geog = result_rest.scalar_one_or_none()

    if not restaurant_geog:
        raise HTTPException(400, "Restaurante sem localização cadastrada.")

    # Calcular Audiência
    radius_meters = (payload.radius_km or 20) * 1000
    stmt_count = select(func.count(Client.id)).where(
        ST_DWithin(Client.geog, restaurant_geog, radius_meters)
    )
    result_count = await db.execute(stmt_count)
    audience_estimate = result_count.scalar() or 0

    # Criar Objeto
    initial_status = "CREATED" if start_time <= now else "SCHEDULED"
    # Importante: Usar start_time e end_time calculados, não o payload bruto
    new_offer = Offer(
        restaurant_id=rid,
        staff_id=staff_id,
        title=payload.title,
        description=payload.message, # Mapeando message -> description
        start_at=start_time, # Variável calculada
        end_at=end_time,     # Variável calculada
        offer_type=payload.offer_type.value, # .value pega a string "FREE_PRODUCT"
        status=initial_status,
        radius_km=payload.radius_km,
        placement=payload.placement,
        price_cents=1000, # Valor fixo por enquanto ou lógica de preço
        accept_limit=payload.accept_limit,
        created_at=now,
        updated_at=now
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
        title=new_offer.title,
        message=new_offer.description,
        accept_limit=new_offer.accept_limit,
        max_target_total=new_offer.max_target_total,
        accept_ttl_hours=new_offer.accept_ttl_hours
        )


@router.patch("/{offer_id}/close", response_model=CloseOfferResponse)
async def close_offer(
    offer_id: int, 
    db: AsyncSession = Depends(get_db_session), 
    staff: dict = Depends(get_current_staff)
):
    # Isso traz a instância da classe que pode ser editada
    stmt = select(Offer).where(
        Offer.id == offer_id,
        Offer.restaurant_id == int(staff["restaurant_id"])
    )
    result = await db.execute(stmt)
    offer_obj = result.scalar_one_or_none()

    # Verifica se a oferta existe
    if not offer_obj:
        raise HTTPException(404, "Oferta não encontrada ou não pertence ao seu restaurante.")

    # 2. Verificar se já não está fechada
    if offer_obj.status in ["CLOSED", "EXPIRED"]:
        raise HTTPException(400, "Oferta já fechada ou expirada.")
    
    # 3. Atualizar Status e Data (Agora funciona porque offer_obj é um Model do SQLAlchemy)
    offer_obj.status = "CLOSED"
    offer_obj.status_reason = "MANUAL_CLOSE"
    offer_obj.closed_at = datetime.now(timezone.utc)
    offer_obj.status_changed_by_staff_id = int(staff["id"])

    # 4. Salvar no banco
    await db.commit()
    await db.refresh(offer_obj)

    return CloseOfferResponse(
        offer_id=offer_obj.id,
        previous_status=offer_obj.status,
        status=offer_obj.status,
        status_reason=offer_obj.status_reason,
        closed_at=offer_obj.closed_at
    )
@router.get("/types")
async def get_offer_types(staff: dict = Depends(get_current_staff)):
    """
    Retorna metadados para o Frontend montar o select de tipos.
    """
    response = []
    
    for type_enum in OfferType:
        # Busca no arquivo de constantes
        meta = OFFER_TYPE_METADATA.get(type_enum.value, {
            "label": type_enum.value, 
            "description": "Oferta especial",
            "icon": "🏷️"
        })
        
        response.append({
            "value": type_enum.value,
            "label": meta["label"],
            "description": meta["description"],
            "icon": meta["icon"]
        })
        
    return response

@router.post("/{offer_id}/publish", response_model=CreateOfferResponse)
async def publish_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    # 1. Buscar a Oferta (Rascunho)
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

    # 2. Buscar o Restaurante (Para pegar GEOG e SALDO DE KM)
    # Mudamos aqui: precisamos do objeto completo para mexer no balance_km
    stmt_rest = select(Restaurant).where(Restaurant.id == offer.restaurant_id)
    res_rest = await db.execute(stmt_rest)
    restaurant = res_rest.scalar_one_or_none()

    if not restaurant:
        raise HTTPException(404, "Restaurante não encontrado.")

    # --- 3. LÓGICA DE COBRANÇA (CARTEIRA DE KM) ---
    radius_needed = int(offer.radius_km or 20)
    
    # Variáveis para salvar na oferta
    cost_in_money = 0.0
    payment_method = "CREDITS"

    # CENÁRIO A: Tem saldo suficiente no pacote?
    if restaurant.balance_km >= radius_needed:
        restaurant.balance_km -= radius_needed # Debita da conta
        payment_method = "CREDITS"
        cost_in_money = 0.0
    # CENÁRIO B: Não tem saldo, cobra avulso
    else:
        payment_method = "PAY_AS_YOU_GO"
        cost_in_money = radius_needed * PRICE_PER_KM_ADHOC

    # Atualiza dados financeiros da oferta
    offer.payment_method = payment_method
    offer.cost_amount = cost_in_money
    # -----------------------------------------------

    # 4. Definir novo Status e Datas
    now = datetime.now(timezone.utc)
    
    # OBS: Mantive sua lógica de forçar start_at = now. 
    # Se quiser agendar futuro, remova a linha 'offer.start_at = now'
    new_status = "ACTIVE" if offer.start_at <= now else "SCHEDULED"
    offer.status = new_status
    offer.start_at = now 

    # 5. GERAR TARGETS (O "Batch" de clientes)
    # Usamos o restaurant.geog que já buscamos no passo 2
    radius_meters = radius_needed * 1000

    stmt_clients = select(Client.id).where(
        ST_DWithin(Client.geog, restaurant.geog, radius_meters)
    ).limit(offer.audience_estimate)
    
    clients_result = await db.execute(stmt_clients)
    client_ids = clients_result.scalars().all()

    # 6. Inserção em Massa (Bulk Insert)
    if client_ids:
        targets_data = [
            {
                "offer_id": offer.id,
                "client_id": cid,
                "status": "PENDING",
                "created_at": now
            } 
            for cid in client_ids
        ]
        await db.execute(insert(OfferTarget), targets_data)

    # 7. Salvar Mudanças (Oferta + Saldo do Restaurante)
    offer.updated_at = now
    await db.commit()
    await db.refresh(offer)

    return CreateOfferResponse(
        offer_id=offer.id,
        staff_id=int(staff["id"]), 
        offer_type=offer.offer_type,
        placement=offer.placement,
        radius_km=offer.radius_km,
        
        # Agora retorna o valor real cobrado (0 se foi crédito, ou valor em centavos)
        price_cents=int(offer.cost_amount * 100), 
        
        audience_estimate=offer.audience_estimate,
        status=offer.status,
        start_at=offer.start_at,
        end_at=offer.end_at
    )

# (Os demais endpoints Update, Close, Repeat seguem o mesmo padrão: Mude apenas a classe do Payload no argumento da função)
