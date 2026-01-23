from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, Annotated, List, Literal, Dict
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
    RestaurantDetailsResponse)

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

@router.get("/restaurants", response_model=List[RestaurantDetailsResponse]) # Use o Schema de Resposta correto
async def get_restaurants_list(
    # Agrupa lat, long, page, limit
    params: Annotated[RestaurantsRequest, Depends()], 
    uid: int = Depends(get_current_client_id), 
    q: Optional[str] = None,
    features: Optional[List[str]] = Query(None), # Ex: ?features=wifi&features=parking
    db: AsyncSession = Depends(get_db_session),
):  
    offset = (params.page - 1) * params.limit
    
    # Dicionário de parâmetros para o SQL
    sql_params = {
        "lat": params.lat,
        "long": params.long,
        "limit": params.limit,
        "offset": offset
    }

    # 1. CLÁUSULAS WHERE DINÂMICAS
    where_clauses = ["is_active = TRUE"]

    # A. Filtro de Distância (20km)
    # IMPORTANTE: ST_MakePoint é (LONGITUDE, LATITUDE)
    where_clauses.append("ST_DWithin(geog, ST_SetSRID(ST_MakePoint(:long, :lat), 4326), 20000)")

    # B. Filtro de Texto (Nome ou Descrição)
    if q:
        where_clauses.append("(name ILIKE :q OR description ILIKE :q)")
        sql_params["q"] = f"%{q}%"

    # C. Filtro de Features (O Pulo do Gato 🐱)
    # Precisamos encontrar restaurantes que tenham TODAS as features solicitadas.
    # Fazemos isso verificando se a contagem de features encontradas bate com a contagem solicitada.
    if features:
        where_clauses.append("""
            EXISTS (
                SELECT 1 
                FROM restaurant_features rf
                JOIN features f ON f.id = rf.feature_id
                WHERE rf.restaurant_id = restaurants.id
                  AND f.slug = ANY(:feature_slugs)
                GROUP BY rf.restaurant_id
                HAVING COUNT(DISTINCT f.slug) = :feature_count
            )
        """)
        sql_params["feature_slugs"] = features
        sql_params["feature_count"] = len(features)

    # Junta todos os filtros com 'AND'
    where_string = " AND ".join(where_clauses)

    # 2. QUERY PRINCIPAL
    # Adicionei uma subquery para já retornar as features formatadas para o Frontend (json_object_agg)
    # Isso evita que o card fique sem os ícones na lista
    query = text(f"""
        SELECT 
            id, 
            name, 
            logo_url, 
            is_open,
            cover_image_url, 
            address_city, 
            address_street as address,
            reputation, 
            -- Subquery para montar o JSON de features para o frontend: {"wifi": true, "parking": true}
            (
                SELECT json_object_agg(f.slug, true)
                FROM restaurant_features rf
                JOIN features f ON f.id = rf.feature_id
                WHERE rf.restaurant_id = restaurants.id
                AND f.is_active = true
            ) as features,
            ST_Distance(geog, ST_SetSRID(ST_MakePoint(:long, :lat), 4326))::int as distance_meters
        FROM restaurants
        WHERE {where_string}
        ORDER BY distance_meters ASC
        LIMIT :limit OFFSET :offset
    """)

    # 3. Execução
    result = await db.execute(query, sql_params)
    rows = result.mappings().all()

    return rows

@router.get("/picks")
async def get_picks(
    params: Annotated[PicksRequest, Depends()], # Agrupa lat, lon e city_slug
    uid: int = Depends(get_current_client_id), 
    db: AsyncSession = Depends(get_db_session),
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


@router.get("/{restaurant_id}/features", response_model=MobileFeaturesResponse)
async def get_restaurant_features(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    # 1. QUERY AJUSTADA:
    # Em vez de pegar 'fg.code' e 'feature_id', pegamos o 'f.slug'
    # O 'slug' é o identificador textual (ex: 'wifi', 'kids', 'ac')
    query = text("""
        SELECT f.slug
        FROM restaurant_features rf
        JOIN features f ON f.id = rf.feature_id
        WHERE rf.restaurant_id = :rid
          AND f.is_active = true 
    """)
    
    # Executa e pega apenas os valores escalares (lista de strings)
    result = await db.execute(query, {"rid": restaurant_id})
    rows = result.scalars().all() # Ex: ['wifi', 'parking', 'kids']

    # 2. TRANSFORMAÇÃO PARA O APP:
    # Converte a lista ['wifi'] em um dicionário {'wifi': True}
    features_map = {slug: True for slug in rows}

    # 3. RETORNO:
    # Envolvemos na chave "features" para bater com o frontend: response.data.features
    return {"features": features_map}

