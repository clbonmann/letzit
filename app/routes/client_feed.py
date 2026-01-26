from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, Annotated, List, Literal, Dict, Union, Any
from uuid import uuid4
from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlalchemy import text, or_, and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db import get_db_session, AsyncSessionLocal
from app.deps_client import get_current_client_id   
from app.models import Restaurant

# IMPORTANDO SCHEMAS
from app.schemas.client import (
    AcceptOfferResponse, 
    PicksRequest, 
    RestaurantsRequest, 
    MobileFeaturesResponse, 
    RestaurantDetailsResponse,
    ClientLocationUpdate)

router = APIRouter(prefix="/client/offers", tags=["client-feed"])

# Função auxiliar para marcar visualização sem travar o request principal
async def mark_offers_as_viewed(uid: int, offer_ids: list, db_session_factory):
    if not offer_ids:
        return
    async with db_session_factory() as db:
        await db.execute(
            text("""
                UPDATE offer_targets 
                SET viewed_at = NOW() 
                WHERE client_id = :uid 
                  AND offer_id = ANY(:oids) 
                  AND viewed_at IS NULL
            """),
            {"uid": uid, "oids": offer_ids}
        )
        await db.commit()

@router.get("/restaurants") # Ajuste o response_model conforme seu arquivo de schemas
async def get_restaurants_list(
    lat: float,
    lon: float,
    page: int = 1,
    limit: int = 10,
    q: Optional[str] = None,
    features: Optional[List[str]] = Query(None), # Ex: ?features=wifi&features=vegan
    db: AsyncSession = Depends(get_db_session),
):  
    offset = (page - 1) * limit
    
    sql_params = {
        "lat": lat,
        "lon": lon,
        "limit": limit,
        "offset": offset
    }

    # 1. CLÁUSULAS WHERE DINÂMICAS
    # Começamos filtrando apenas os ativos
    where_clauses = ["is_active = TRUE"]

    # Filtro de Distância (Raio de 20km)
    # Nota: ST_MakePoint é (Longitude, Latitude)
    where_clauses.append("ST_DWithin(geog::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 25000)")

    # Filtro de Texto (Nome ou Descrição)
    if q:
        where_clauses.append("(name ILIKE :q OR description ILIKE :q)")
        sql_params["q"] = f"%{q}%"

    # Filtro de Features (Relacional - AND Lógico)
    # O usuário deve ter TODAS as features solicitadas
    if features:
        where_clauses.append("""
            EXISTS (
                SELECT 1 
                FROM restaurant_features rf
                JOIN features f ON f.id = rf.feature_id
                WHERE rf.restaurant_id = restaurants.id
                  AND f.slug = ANY(:feature_slugs::text[]) 
                GROUP BY rf.restaurant_id
                HAVING COUNT(DISTINCT f.slug) = :feature_count
            )
        """)
        sql_params["feature_slugs"] = features
        sql_params["feature_count"] = len(features)

    where_string = " AND ".join(where_clauses)

    # 2. QUERY PRINCIPAL
    # O subselect 'features' retorna um JSON { "wifi": true, "parking": true }
    query = text(f"""
        SELECT 
            r.id, 
            r.name, 
            r.description, 
            r.logo_url, 
            r.cover_image_url,
            r.is_open,
            r.reputation,
            r.address_street, 
            r.address_city, 
            
            -- CAMPOS DE CONTATO E SOCIAL (FALTAVAM AQUI)
            r.phone,
            r.whatsapp,
            r.instagram,
            r.facebook,
            r.tiktok,
            r.tripadvisor,
            r.site,
            
            -- Extrai Lat/Lon do PostGIS para mostrar no mapa se precisar
            ST_Y(r.geog::geometry) as lat,
            ST_X(r.geog::geometry) as lon,
            (
                SELECT json_object_agg(f.slug, true)
                FROM restaurant_features rf
                JOIN features f ON f.id = rf.feature_id
                WHERE rf.restaurant_id = r.id
                AND f.is_active = true
            ) as features,
            
            -- Cálculo exato em metros
            ST_DistanceSphere(r.geog::geometry, ST_MakePoint(:lon, :lat)) as distance_meters

        FROM restaurants r
        WHERE {where_string}
        ORDER BY distance_meters ASC
        LIMIT :limit OFFSET :offset
    """)

    result = await db.execute(query, sql_params)
    rows = result.mappings().all()

    # Retorna lista direta (FastAPI converte para JSON array)
    return rows

@router.get("/picks")
async def get_picks(
    bg: BackgroundTasks,
    params: Annotated[PicksRequest, Depends()], # Agrupa lat, lon e city_slug
    uid: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db_session)
):  
    
    # Agora você acessa via params.lat, params.lon, etc.
    lat = params.lat
    lon = params.lon
    city_slug = params.city_slug
    placement = params.placement

    # Ponto geográfico de referência (usado para ordenar a lista final)
    # Se lat/lon não vierem, usamos a última localização do cliente no banco
    ref_point = f"ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)" if lat and lon else "c.geog"

    # 1. Busca ofertas já selecionadas pelo Matchmaker para este cliente
    # Esta é a query principal: rápida e indexada pela tabela offer_targets
    query_targets = text(f"""
        SELECT 
            o.id, 
            o.restaurant_id, 
            r.name AS restaurant_name, 
            r.logo_url, 
            r.reputation,
            o.title, 
            o.message, 
            o.price_cents,
            o.original_price_cents,
            o.end_at, 
            ST_Distance(r.geog, {ref_point})::int as distance_m, 
            o.placement
        FROM offer_targets t 
        JOIN offers o ON o.id = t.offer_id 
        JOIN restaurants r ON r.id = o.restaurant_id
        JOIN clients c ON c.id = t.client_id
        WHERE t.client_id = :uid 
          AND o.placement = :placement
          AND t.accepted_at IS NULL 
          AND o.status = 'ACTIVE' 
          AND o.end_at > NOW()
          AND (o.accept_limit - o.accepted_count) > 0
        ORDER BY t.created_at DESC 
        LIMIT 10
    """)
    
    rows = (await db.execute(query_targets, {"uid": uid, "placement": placement })).mappings().all()
# 2. Se encontrou ofertas, agenda a marcação de visualização
    if rows:
        offer_ids = [row['id'] for row in rows]
        # Usamos background_tasks para o update não "pesar" no tempo de resposta do app
        bg.add_task(mark_offers_as_viewed, uid, offer_ids, lambda: db)
    return {
        "strategy": "TARGETED" if rows else "EMPTY",
        "title": "Sugestões para Você",
        "items": rows
    }

@router.get("/features")
async def get_features_unified(
    # 2. 'Query(None)' torna o parâmetro opcional na URL.
    # Se não enviar, restaurant_id será None.
    restaurant_id: Optional[int] = Query(None, description="ID opcional do restaurante"),
    
    # 3. Apenas sessão do banco. SEM dependência de usuário logado (uid).
    db: AsyncSession = Depends(get_db_session),
):
    """
    Retorna filtros gerais (se sem ID) ou features de um restaurante (se com ID).
    Público: Não requer login.
    """

    # CASO A: Tem ID -> Retorna Dict {"features": {"wifi": true}}
    if restaurant_id:
        query = text("""
            SELECT f.slug
            FROM restaurant_features rf
            JOIN features f ON f.id = rf.feature_id
            WHERE rf.restaurant_id = :rid
              AND f.is_active = true 
        """)
        
        result = await db.execute(query, {"rid": restaurant_id})
        rows = result.scalars().all()

        features_map = {slug: True for slug in rows}
        return {"features": features_map}

    # CASO B: Sem ID -> Retorna Lista [{'slug': 'wifi', 'name': 'Wi-Fi'}]
    else:
        query = text("SELECT slug, name FROM features WHERE is_active = true ORDER BY name")
        result = await db.execute(query)
        
        return result.mappings().all()
    
@router.get("/map-source")
async def get_offers_map_source(db: AsyncSession = Depends(get_db_session)):
    query = text("""
        SELECT json_build_object('type', 'FeatureCollection', 'features', json_agg(ST_AsGeoJSON(t.*)::json))
        FROM (
            SELECT ST_SetSRID(ST_MakePoint(ST_X(r.geog::geometry), ST_Y(r.geog::geometry)), 4326) as geometry,
            json_build_object('offer_id', o.id, 'title', o.title, 'price_cents', o.price_cents, 'restaurant_name', r.name, 
            'logo_url', r.logo_url, r.reputation, 'type', o.placement) as properties
            FROM offers o JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.status = 'ACTIVE' AND o.end_at > NOW() AND o.accepted_count < o.accept_limit
        ) as t;
    """)
    res = (await db.execute(query)).scalar()
    return res if res else {"type": "FeatureCollection", "features": []}

@router.get("/{offer_id}")
async def get_offer_details(offer_id: int, uid: int = Depends(get_current_client_id), db: AsyncSession = Depends(get_db_session)):
    query = text("""
        SELECT o.id, o.title, o.description, o.message, o.price_cents, o.original_price_cents, 
        o.end_at, o.placement, r.name as restaurant_name, r.logo_url, r.cover_image_url, r.address_street,
         r.address_number, r.phone, ST_Y(r.geog::geometry) as lat, ST_X(r.geog::geometry) as lon FROM offers o 
        JOIN restaurants r ON r.id = o.restaurant_id WHERE o.id = :oid
    """)
    
    row = (await db.execute(query, {"oid": offer_id})).mappings().first()
    if not row: raise HTTPException(404, "Oferta não encontrada")
    return row

@router.post("/{offer_id}/accept", response_model=AcceptOfferResponse)
async def accept_offer(
    offer_id: int, 
    bg: BackgroundTasks, 
    db: AsyncSession = Depends(get_db_session), 
    uid: int = Depends(get_current_client_id)
):
    now = datetime.now(timezone.utc)

    # 1. Verifica se o usuário foi "pescado" (Targeted) e se já tem um Claim
    # Isso substitui os checks de bloqueio/cooldown que o Matchmaker já fez.
    query = text("""
        SELECT 
            t.offer_id, 
            c.status as claim_status, 
            c.expires_at, 
            c.qr_token 
        FROM offer_targets t
        LEFT JOIN offer_claims c ON c.offer_id = t.offer_id AND c.client_id = t.client_id
        WHERE t.offer_id = :oid AND t.client_id = :uid
    """)
    
    check = (await db.execute(query, {"oid": offer_id, "uid": uid})).mappings().first()
    
    # Se não existe na offer_targets, o usuário não tem direito a esta oferta (segurança)
    if not check:
        return AcceptOfferResponse(status="NOT_ELIGIBLE", offer_id=offer_id)
    
    # Se já aceitou anteriormente, retorna o ticket existente (Idempotência)
    if check.claim_status:
        return AcceptOfferResponse(
            status="ACCEPTED" if check.claim_status == "ACCEPTED" else "CLOSED",
            offer_id=offer_id,
            expires_at=check.expires_at,
            qr_token=check.qr_token
        )

    # 2. Bloqueio de Oferta e Checagem de Estoque/Status
    # Usamos FOR UPDATE para evitar que dois usuários peguem a última vaga ao mesmo tempo
    o = (await db.execute(
        text("SELECT id, status, end_at, accept_limit, accepted_count, accept_ttl_hours FROM offers WHERE id=:oid FOR UPDATE"),
        {"oid": offer_id}
    )).mappings().first()

    if not o or o.status != "ACTIVE" or o.end_at <= now:
        return AcceptOfferResponse(status="CLOSED", offer_id=offer_id)
    
    if o.accepted_count >= o.accept_limit:
        return AcceptOfferResponse(status="SOLD_OUT", offer_id=offer_id)

    # 3. Processamento do Resgate (Claim)
    ttl = o.accept_ttl_hours or 6
    exp = min(o.end_at, now + timedelta(hours=ttl))
    qr = str(uuid4())

    try:
        # Insere o Cupom
        await db.execute(
            text("""
                INSERT INTO offer_claims (offer_id, client_id, status, accepted_at, expires_at, qr_token) 
                VALUES (:oid, :uid, 'ACCEPTED', :now, :exp, :qr)
            """), 
            {"oid": offer_id, "uid": uid, "now": now, "exp": exp, "qr": qr}
        )

        # Atualiza Contagem da Oferta
        await db.execute(
            text("UPDATE offers SET accepted_count = accepted_count + 1 WHERE id = :oid"),
            {"oid": offer_id}
        )

        # Atualiza o Target para marcar que a pescaria foi bem sucedida
        await db.execute(
            text("UPDATE offer_targets SET accepted_at = :now WHERE client_id = :uid AND offer_id = :oid"),
            {"uid": uid, "oid": offer_id, "now": now}
        )

        await db.commit()
                
        return AcceptOfferResponse(
            status="ACCEPTED", 
            offer_id=offer_id, 
            client_id=uid, 
            expires_at=exp, 
            qr_token=qr, 
            accepted_count=o.accepted_count + 1, 
            accept_limit=o.accept_limit
        )

    except Exception as e:
        await db.rollback()
        raise e
    
@router.get("/my-claims")
async def get_my_claims(
    uid: int = Depends(get_current_client_id), 
    db: AsyncSession = Depends(get_db_session)
):
    """
    Retorna os cupons ATIVOS do usuário (Status 'ACCEPTED').
    """
    query = text("""
        SELECT 
            c.id as claim_id,
            c.qr_token,
            c.expires_at,
            c.status,
            o.title,
            r.name as restaurant_name,
            r.logo_url,
            r.reputation
        FROM offer_claims c
        JOIN offers o ON o.id = c.offer_id
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE c.client_id = :uid 
        AND c.status = 'ACCEPTED'
        AND c.expires_at > NOW()
        ORDER BY c.expires_at ASC
    """)
    
    rows = (await db.execute(query, {"uid": uid})).mappings().all()
    return rows

@router.post("/{offer_id}/click")
async def register_offer_click(
    offer_id: int,
    uid: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Registra que o usuário clicou para ver os detalhes de uma oferta específica.
    """
    await db.execute(
        text("""
            UPDATE offer_targets 
            SET clicked_at = NOW() 
            WHERE client_id = :uid 
              AND offer_id = :oid 
              AND clicked_at IS NULL
        """),
        {"uid": uid, "oid": offer_id}
    )
    await db.commit()
    return {"status": "recorded"}

@router.get("/restaurants/{restaurant_id}")
async def get_restaurant_details(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Retorna os detalhes completos de um restaurante específico + suas features.
    """
    query = text("""
        SELECT 
            r.id, 
            r.name, 
            r.description, 
            r.logo_url, 
            r.cover_image_url,
            r.is_open,
            r.reputation,
            r.address_street, 
            r.address_city, 
            
            -- Extrai Lat/Lon do PostGIS para mostrar no mapa se precisar
            ST_Y(r.geog::geometry) as lat,
            ST_X(r.geog::geometry) as lon,

            -- Subquery para montar as features: {"wifi": true, "parking": true}
            (
                SELECT json_object_agg(f.slug, true)
                FROM restaurant_features rf
                JOIN features f ON f.id = rf.feature_id
                WHERE rf.restaurant_id = r.id
                AND f.is_active = true
            ) as features

        FROM restaurants r
        WHERE r.id = :rid 
          AND r.is_active = true
    """)

    result = await db.execute(query, {"rid": restaurant_id})
    restaurant = result.mappings().first()

    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante não encontrado ou inativo.")

    return restaurant

from app.schemas.client import ClientLocationUpdate

@router.post("/location")
async def update_client_location(
    payload: ClientLocationUpdate,
    db: AsyncSession = Depends(get_db_session),
    client: dict = Depends(get_current_client_id)
):
    """
    Atualiza a geolocalização do cliente logado.
    Salva como um ponto geográfico (PostGIS) para cálculos rápidos de distância.
    """
    client_id = client["id"]

    try:
        # Atualiza a coluna 'last_location' ou 'geog' na tabela de users/clients
        # ST_SetSRID(ST_MakePoint(lon, lat), 4326) cria o ponto GPS padrão
        query = text("""
            UPDATE users 
            SET 
                geog = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                last_loc_at = NOW()
            WHERE id = :uid
        """)
        
        await db.execute(query, {
            "lat": payload.lat, 
            "lon": payload.lon, 
            "uid": client_id
        })
        await db.commit()
        
        return {"status": "updated", "lat": payload.lat, "lon": payload.lon}

    except Exception as e:
        print(f"Erro ao atualizar localização: {e}")
        await db.rollback()
        # Não queremos travar o app se isso falhar, então pode retornar erro ou silenciar
        raise HTTPException(status_code=500, detail="Erro ao salvar localização")