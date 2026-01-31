from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import List, Literal, Optional
import traceback
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Header
from shapely import Geometry
from geoalchemy2.shape import from_shape
from sqlalchemy import and_, exists, insert, text, select, func, cast
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.functions import ST_DWithin
from geoalchemy2.shape import from_shape, to_shape # Importações para conversão de geometrias
from geoalchemy2 import Geometry as GAGeometry
# Imports do App
from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.constants.pricing import PRICE_PER_TA_ADHOC
from app.constants.offer_types import OFFER_TYPE_METADATA
from app.services.storage import upload_image  # Certifique-se que esta função existe no seu projeto
from app.services.finance import process_transaction

# Models e Schemas
from app.models import Offer, OfferTarget, Store, Client, OfferType, ClientFavourite
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
    staff: dict = Depends(get_current_staff),
    x_store_id: int | None = Header(default=None, alias="x-store-id"),
):
    logged_rid = int(staff["store_id"])
    store_id = logged_rid

    # Lógica Super Admin
    if staff.get("role") == "INTERNAL_ADMIN" and x_store_id:
        store_id = x_store_id
        
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
                folder=f"stores/{store_id}/offers/",
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
    staff: dict = Depends(get_current_staff),
    x_store_id: int | None = Header(default=None, alias="x-store-id"),
):
    logged_rid = int(staff["store_id"])
    store_id = logged_rid

    # Lógica Super Admin
    if staff.get("role") == "INTERNAL_ADMIN" and x_store_id:
        store_id = x_store_id

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
        WHERE o.store_id = :rid
    """
    
    params = {"rid": store_id, "limit": limit}
    
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

@router.get("/audience-estimation")
async def estimate_audience(
    radius_km: int = Query(..., ge=1, le=100, description="Raio em KM"),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
    x_store_id: int | None = Header(default=None, alias="x-store-id"),
):
    logged_sid = int(staff["store_id"])
    sid = logged_sid
    active_threshold = datetime.now(timezone.utc) - timedelta(minutes=15)  

    if staff.get("role") == "INTERNAL_ADMIN" and x_store_id:
        sid = x_store_id

    # 1. Busca Localização do estabelecimento
    stmt_rest = select(Store.geog).where(Store.id == sid)
    store_geog = (await db.execute(stmt_rest)).scalar_one_or_none()

    if not store_geog:
        return {"radius_km": radius_km, "estimated_audience": 0, "points": []}

    # --- CORREÇÃO AQUI ---
    # 1. to_shape: Converte o WKBElement do banco para um objeto Shapely (Python)
    # 2. from_shape: Converte o objeto Shapely de volta para um Elemento SQL com SRID correto
 
    # 2. Converte KM para Metros
    radius_meters = radius_km * 1000

    # 3. Filtros
    filters = [
        ST_DWithin(Client.geog, store_geog, radius_meters),
        Client.is_blocked == False,
        Client.is_deleted == False,
        Client.geog.is_not(None),
        Client.last_loc_at >= active_threshold 
    ]

    # 4. Contagem Total
    count = (await db.execute(select(func.count(Client.id)).where(*filters))).scalar() or 0
  
    # 5. Amostra de Pontos (Limitado a 100)
    stmt_points = select(
        func.ST_Y(cast(Client.geog, GAGeometry)).label("lat"),
        func.ST_X(cast(Client.geog, GAGeometry)).label("lng")
    ).where(*filters).limit(100)

    points_rows = (await db.execute(stmt_points)).all()
    real_points = [{"lat": row.lat, "lng": row.lng} for row in points_rows]

    return {
        "radius_km": radius_km,
        "estimated_audience": count,
        "points": real_points
    }
# --- ENDPOINT 2: COTAÇÃO ---
@router.post("/quote", response_model=QuoteResponse)
async def quote_offer(
    payload: QuoteRequest, 
    db: AsyncSession = Depends(get_db_session), 
    staff: dict = Depends(get_current_staff)
):  
    
    sid = int(staff["store_id"])

    # 1. Buscar estabelecimento (Geo + Saldo de targets)
    stmt_store = select(Store).where(Store.id == sid)
    result_store = await db.execute(stmt_store)
    store = result_store.scalar_one_or_none()

    if not store or not store.geog:
        raise HTTPException(400, "Localização do estabelecimento inválida.")

    if payload.placement == 'CITY_HOME':
        # Se for Destaque Home, verifica o saldo específico de Home
        if store.balance_home <= 0:
            raise HTTPException(
                status_code=402, # 402 Payment Required (Semântico) ou 400
                detail="Saldo de 'Destaque Home' insuficiente. Adquira um pacote na loja para usar este formato."
            )
            
    else: 
        # Se for NORMAL (ou qualquer outro), verifica o saldo de Iscas (BT)
        if store.balance_ta <= 0:
            raise HTTPException(
                status_code=402,
                detail="Seu saldo de Iscas (BT) está zerado. Você precisa comprar targets para criar ofertas de raio."
            )

    projected_balance_ta = store.balance_ta
    projected_balance_home = store.balance_home
    price_cents = store.cost_ta_cents or 0
    quote_msg = ""
    consumption = 0
    
    # 2. Buscar Audiência Estimada com base nos filtros
  
    # PLACEMENT "NORMAL"
    if payload.placement == "NORMAL":
        if not payload.radius_km:
            raise HTTPException(400, "O raio de ação é obrigatório para este tipo de oferta.")

    radius_km = int(payload.radius_km)
    radius_meters = radius_km * 1000
    audience_estimate=0    
    active_threshold = datetime.now(timezone.utc) - timedelta(minutes=15)

    stmt = select(func.count(Client.id)).where(
    and_(
        Client.is_deleted.is_(False),
        Client.is_blocked.is_(False),
        Client.geog.is_not(None),
        Client.last_loc_at >= active_threshold, # <--- Filtro dos 15 minutos
        ST_DWithin(Client.geog, store.geog, radius_meters)
            )
    )

    # 3. Filtros Opcionais (Demográficos)
    
    # Filtro: Maioridade
    if payload.is_adult:
        stmt = stmt.where(Client.is_adult.is_(True))

        # Filtro: Gênero (M, F, O)
    if payload.gender and payload.gender != 'ALL':
        stmt = stmt.where(Client.gender == payload.gender)

        # Filtro: Nível Mínimo
    if payload.min_level and payload.min_level > 0:
        stmt = stmt.where(Client.level >= payload.min_level)

        # Filtro: Reputação Mínima
    if payload.min_reputation and payload.min_reputation > 0:
        stmt = stmt.where(Client.reputation >= payload.min_reputation)

        # 4. Filtro Complexo: "Sou Favorito"
        # Lógica: O cliente precisa ter um registro na tabela client_favorites 
        # que aponte para este restaurante.
    if payload.is_preferred:
        favorite_subquery = select(1).where(
            and_(
                ClientFavourite.client_id == Client.id,
                ClientFavourite.favourite_id == store.id,
                ClientFavourite.group_id == 1
            )
        )
        stmt = stmt.where(exists(favorite_subquery))

       
    # 5. Execução
    result = await db.execute(stmt)
    audience_estimate = result.scalar() or 0
    if audience_estimate > payload.max_target_total:
        audience_estimate = payload.max_target_total
    # Calcular Preço
        
        
    if payload.placement == "NORMAL":

        projected_balance_ta = store.balance_ta - audience_estimate

        if  projected_balance_ta >= 0:
            price_cents = audience_estimate * price_cents 
            quote_msg = f"Preço baseado no valor atual ddo seu estoque de targets ({store.balance_ta})."
        else:
            price_cents = 0
            quote_msg = "Seu saldo de targets (TA) é insuficiente para atingir toda a audiência estimada."
    else:
        price_cents = 0  
        quote_msg = "Preço fixo para destaque na Home da Cidade."
        projected_balance_home = store.balance_home - 1
        quote_msg = "Preço fixo (1 Crédito Home) para destaque na cidade."

    # Garante que price_cents seja um inteiro (0 se for None)
    safe_price_cents = int(price_cents or 0)

    return {
        # Campos de Audiência e Custo
        "audience_estimate": audience_estimate, # Antes estava 'available_audience'? Ajuste para o nome do Schema
        "capped_audience": payload.max_target_total,
        "cost": round(safe_price_cents / 100, 2), # Opcional, se seu front usa
        "price_cents": safe_price_cents,
        "message": quote_msg,
        
        # --- CORREÇÃO: Adicionando os campos que o Pydantic reclamou que faltavam ---
        "placement": payload.placement,
        "radius_km": payload.radius_km, # Pode ser None se for CITY_HOME, verifique se o Schema permite Optional[int]
        
        # Saldos
        "balances": {
            "current_ta": store.balance_ta,
            "projected_ta": projected_balance_ta,
            "current_home": store.balance_home,
            "projected_home": projected_balance_home
        }
    }
        
    # PLACEMENT "CITY_HOME"
    if payload.placement == "CITY_HOME":
               
        stmt_home = select(func.count(Client.id)).where(
        and_(
            Client.deleted_at.is_(None),
            Client.is_blocked.is_(False),
            Client.last_loc_at >= active_threshold, # <--- Filtro dos 15 minutos
            ST_DWithin(Client.geog, store.geog, radius_meters)
            )
        )
        audience = (await db.execute(stmt_home)).scalar() or 0

        return QuoteResponse(
            placement="CITY_HOME",
            radius_km=radius_km,
            price_cents=price_cents,
            wallet_balance_ta=store.balance_ta,
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
    staff: dict = Depends(get_current_staff),
    x_store_id: int | None = Header(default=None, alias="x-store-id"),
):
    logged_rid = int(staff["store_id"])
    rid = logged_rid

    # Lógica Super Admin
    if staff.get("role") == "INTERNAL_ADMIN" and x_store_id:
        rid = x_store_id

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
    stmt_rest = select(Store.geog).where(Store.id == rid)
    result_rest = await db.execute(stmt_rest)
    store_geog = result_rest.scalar_one_or_none()

    if not store_geog:
        raise HTTPException(400, "estabelecimento sem localização cadastrada.")

    # --- 3. Calcular Audiência ---
    radius_km = payload.radius_km or 25 # Default 25km
    radius_meters = radius_km * 1000
    
    stmt_count = select(func.count(Client.id)).where(
        ST_DWithin(Client.geog, store_geog, radius_meters)
    )
    result_count = await db.execute(stmt_count)
    audience_estimate = result_count.scalar() or 0

    # --- 4. Criar Objeto ---
    # AJUSTE: Forçamos o status inicial para 'CREATED' (Rascunho)
    # Isso obriga a chamar o endpoint /publish para efetivar o débito financeiro.
    initial_status = "CREATED" 
    
    offer_type_val = payload.offer_type.value if hasattr(payload.offer_type, 'value') else payload.offer_type

    new_offer = Offer(
        store_id=rid,
        staff_id=staff_id,
        title=payload.title,
        description=payload.message,
        offer_image_url=payload.offer_image_url,
        start_at=start_time,
        end_at=end_time,
        offer_type=offer_type_val,
        status=initial_status,
        radius_km=radius_km,
        placement=payload.placement,
        price_cents=payload.price_cents or 0,
        original_price_cents=payload.original_price_cents or 0,
        accept_limit=payload.accept_limit,
        max_target_total=payload.max_target_total,
        audience_estimate=audience_estimate,
        created_at=now,
        updated_at=now,
        geog=store_geog
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
    staff: dict = Depends(get_current_staff),
    x_store_id: int | None = Header(default=None, alias="x-store-id"),
):
    logged_rid = int(staff["store_id"])
    rid = logged_rid

    # Lógica Super Admin
    if staff.get("role") == "INTERNAL_ADMIN" and x_store_id:
        rid = x_store_id

    stmt = select(Offer).where(
        Offer.id == offer_id,
        Offer.store_id == rid
    )
    result = await db.execute(stmt)
    offer_obj = result.scalar_one_or_none()

    if not offer_obj:
        raise HTTPException(404, "Oferta não encontrada ou não pertence ao seu estabelecimento.")

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

@router.post("/{offer_id}/publish", response_model=CreateOfferResponse)
async def publish_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
    x_store_id: int | None = Header(default=None, alias="x-store-id"),
):
    logged_rid = int(staff["store_id"])
    rid = logged_rid

    if staff.get("role") == "INTERNAL_ADMIN" and x_store_id:
        rid = x_store_id

    # Buscar Oferta e estabelecimento
    stmt = select(Offer).where(Offer.id == offer_id, Offer.store_id == rid)
    result = await db.execute(stmt)
    offer = result.scalar_one_or_none()

    if not offer:
        raise HTTPException(404, "Oferta não encontrada.")
    
    if offer.status != "CREATED":
        raise HTTPException(400, "Apenas ofertas com status 'CREATED' podem ser publicadas.")

    # --- LÓGICA DE DÉBITO FINANCEIRO ---
    # 1. Definir o custo em KM (Regra: 100 KM por 1km de raio, por exemplo)
    # Você pode ajustar essa regra de acordo com o app.constants.pricing
    radius_val = int(offer.radius_km)* -1

    #print(f"Calculando débito de {radius_val} KM para oferta {offer.id}")

    try:
        # 2. Chamar o Service Financeiro (Isso garante lock, histórico e validação)
        # Note o sinal NEGATIVO (-) para indicar débito (saída)
        transaction = await process_transaction(
            db=db,
            store_id=rid,
            amount=radius_val, # Débito em KM
            value=0.0, # Sem valor monetário na publicação, consome crédito
            description_data={
                "offer_id": offer.id,
                "action": "PUBLISH_OFFER",
                "radius_km": radius_val
            }
        )
    except HTTPException as e:
        # Repassa o erro de saldo insuficiente (400) para o front
        raise e
    except Exception as e:
        print(f"Erro financeiro: {e}")
        raise HTTPException(500, "Erro ao processar débito da oferta.")

    # --- ATUALIZAR STATUS DA OFERTA ---
    now = datetime.now(timezone.utc)
    
    # Se a data de início é futuro, vira SCHEDULED. Se é passado/agora, vira ACTIVE.
    new_status = "ACTIVE" if offer.start_at <= now else "SCHEDULED"
    
    offer.status = new_status
    # offer.start_at = now # REMOVIDO: Respeita o agendamento se foi criado no futuro
    offer.updated_at = now
    
    # Salvar custo na oferta para referência rápida
    offer.cost_amount = 0 # Custo monetário direto é 0 (foi crédito)
    # Você pode criar uma coluna 'cost_km' na tabela Offer se quiser salvar quanto custou em KM
    
    await db.commit()
    await db.refresh(offer)

    return CreateOfferResponse(
        offer_id=offer.id,
        staff_id=int(staff["id"]), 
        offer_type=offer.offer_type,
        placement=offer.placement,
        radius_km=offer.radius_km,
        price_cents=int(offer.price_cents), 
        audience_estimate=offer.audience_estimate,
        status=offer.status,
        start_at=offer.start_at,
        end_at=offer.end_at
    )