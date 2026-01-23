from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Literal, Dict, Optional, Set

from geopy.geocoders import Nominatim
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2 import WKTElement

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.schemas.client import get_address_from_coords
from app.utils.cnpj import normalize_cnpj 
from app.services.storage import upload_image 
from app.schemas.staff import (
    RestaurantRead, 
    RestaurantUpdate, 
    RestaurantFeaturesResponse, 
    RestaurantFeaturesUpdateRequest, 
    RestaurantFeaturesUpdateResponse, 
    TaxGroup,
    TaxItem, 
    RestaurantStatusUpdate
)
from app.models import Restaurant, RestaurantStaff as Staff

router = APIRouter(prefix="/staff/restaurant", tags=["staff-restaurant"])

# --- Helper Functions ---

def _is_internal_admin(staff: dict) -> bool:
    return staff.get("role") == "INTERNAL_ADMIN" or int(staff.get("restaurant_id", 0)) == 1

def _require_can_manage_restaurant(staff: dict, restaurant_id: int) -> None:
    if _is_internal_admin(staff):
        return
    if int(staff["restaurant_id"]) != int(restaurant_id):
        raise HTTPException(status_code=403, detail="Not allowed for this restaurant")

def _require_admin_role(staff: dict) -> None:
    role = staff.get("role")
    if role not in ("INTERNAL_ADMIN", "REST_ADMIN"):
        raise HTTPException(status_code=403, detail="Admin role required")

# --- Standard Restaurant Endpoints (List, Update, Upload) ---
# These remain largely the same but are included for completeness of the file

@router.get("", response_model=List[RestaurantRead])
async def list_my_restaurants(
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    List restaurants.
    - INTERNAL_ADMIN: Sees all.
    - Normal Staff: Sees only their own.
    """
    role = str(staff.get("role") or "")
    rid = int(staff.get("restaurant_id") or 0)

    base_sql = """
        SELECT id, name, cnpj, logo_url, reputation,
               address_street, address_number, address_district,
               address_city, address_state, address_zip, address_country, description, phone, is_open, working_hours,
               ST_Y(geog::geometry) as lat,
               ST_X(geog::geometry) as long
        FROM restaurants
    """

    if role == "INTERNAL_ADMIN":
        query = text(f"{base_sql} ORDER BY id DESC")
        params = {}
    else:
        query = text(f"{base_sql} WHERE id = :rid")
        params = {"rid": rid}

    rows = (await db.execute(query, params)).mappings().all()
    
    if role != "INTERNAL_ADMIN" and not rows:
        raise HTTPException(404, "Restaurante vinculado não encontrado.")

    return [RestaurantRead(**row) for row in rows]


@router.patch("", response_model=RestaurantRead)
async def update_restaurant_details(
    payload: RestaurantUpdate,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Atualiza dados do restaurante dinamicamente.
    """
    role = str(staff.get("role") or "")
    
    # 1. Definição do ID
    if role == "INTERNAL_ADMIN":
        if not payload.id:
            raise HTTPException(400, "Admin deve informar o 'id' do restaurante.")
        rid = payload.id
    else:
        rid = int(staff.get("restaurant_id") or 0)

    # 2. Busca o restaurante existente (ORM)
    # Importante para validar existência e comparar CNPJ antigo
    current_restaurant = (await db.execute(select(Restaurant).where(Restaurant.id == rid))).scalars().first()
    
    if not current_restaurant:
        raise HTTPException(404, "Restaurante não encontrado.")

    # 3. Prepara os dados dinâmicos
    # exclude_unset=True pega apenas o que foi enviado no JSON
    update_data = payload.model_dump(exclude_unset=True)

    # Remove o 'id' do dict de update, pois não devemos alterar a PK
    update_data.pop("id", None)

    # --- Lógicas Específicas ---

    # A. Tratamento de CNPJ
    if "cnpj" in update_data :
        normalized = normalize_cnpj(update_data["cnpj"])
        if normalized and role == "INTERNAL_ADMIN":
            if len(normalized) != 14:
                raise HTTPException(400, "CNPJ deve conter 14 dígitos.")
            update_data["cnpj"] = normalized
        else:
            # Se enviou cnpj null/vazio, mantém o antigo ou trata como quiser
            # Aqui removo para não alterar se for inválido, ou mantenho lógica antiga
            update_data.pop("cnpj") 

    # B. Tratamento de Geometria (PostGIS)
    # Se lat E long foram enviados, atualiza o campo geog
    if "lat" in update_data and "long" in update_data:
        lat = update_data.pop("lat", None)   # Pega o valor e REMOVE a chave
        long = update_data.pop("long", None)
        if lat is not None and long is not None:
            # Cria o ponto WKT (Well-Known Text) com SRID 4326
            update_data["geog"] = WKTElement(f"POINT({long} {lat})", srid=4326)
            address_info = get_address_from_coords(lat, long)
            if address_info:
                update_data["address_city"] = address_info['city']
                update_data["address_state"] = address_info['state'] 
    # C. Timestamp da Logo
    if "logo_url" in update_data and update_data["logo_url"]:
        update_data["logo_updated_at"] = datetime.now(timezone.utc)
    
    update_data["updated_at"] = datetime.now(timezone.utc)

    # Se não sobrou nada para atualizar, retorna o atual
    if not update_data:
        return current_restaurant

    try:
        # 4. Executa o Update (SQLAlchemy Core/ORM)
        stmt = (
             update(Restaurant)
            .where(Restaurant.id == rid)
            .values(**update_data)
            .returning(Restaurant)
        )
        
        result = await db.execute(stmt)
        updated_restaurant = result.scalars().first()
        
        await db.commit()
        return updated_restaurant

    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Dados conflitantes (ex: CNPJ já registrado).")


@router.post("/logo")
async def upload_restaurant_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    """Upload Logo to Cloudinary + DB Update."""
    restaurant_id = int(staff["restaurant_id"])

    try:
        transformations = {
            "width": 150, 
            "height": 150, 
            "crop": "pad",
            "background": "white",
            "gravity": "center",
            "quality": "auto",
            "fetch_format": "auto"
        }

        url = upload_image(
            file, 
            folder=f"restaurants/{restaurant_id}",
            transformation=transformations 
        )
        
    except Exception as e:
        print(f"Upload Error: {e}")
        raise HTTPException(500, "Falha no upload da imagem.")

    await db.execute(
        text("UPDATE restaurants SET logo_url = :url, logo_updated_at = NOW() WHERE id = :rid"),
        {"url": url, "rid": restaurant_id}
    )
    await db.commit()

    return {"status": "success", "logo_url": url}

@router.post("/cover")
async def upload_restaurant_cover(
    files: List[UploadFile] = File(...), 
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    """Upload de múltiplas capas para o Cloudinary + Update no Banco."""
    restaurant_id = int(staff["restaurant_id"])

    # 1. Busca as capas atuais para validar limite
    query_select = text("SELECT cover_image_url FROM restaurants WHERE id = :rid")
    current_res = await db.execute(query_select, {"rid": restaurant_id})
    current_cover_str = current_res.scalar()

    cover_list = []
    if current_cover_str:
        cover_list = [c for c in current_cover_str.split(";") if c.strip()]

    # 2. Validação de Limite
    if len(cover_list) + len(files) > 5:
        raise HTTPException(
            status_code=400, 
            detail=f"Limite excedido. Você já tem {len(cover_list)} fotos. Máximo é 5."
        )

    # Configuração do Cloudinary (Use 'fill' e não 'cover')
    transformations = {
        "width": 600, 
        "height": 400, 
        "crop": "fill",  # Garante o corte exato sem distorção
        "gravity": "center",
        "quality": "auto",
        "fetch_format": "auto"
    }

    new_urls = []

    try:
        # 3. Loop de Upload
        for file in files:
            # --- TRUQUE PARA CORRIGIR O ERRO 500 ---
            # O Cloudinary precisa do arquivo bruto (file.file) para leitura síncrona.
            # Mas sua função upload_image precisa do content_type.
            # Então pegamos o arquivo bruto e adicionamos o content_type nele manualmente.
            file_object = file.file
            setattr(file_object, "content_type", file.content_type)
            
            # Agora passamos o objeto síncrono, mas com o atributo content_type
            url = upload_image(
                file_object, 
                folder=f"restaurants/{restaurant_id}/cover",
                transformation=transformations 
            )
            new_urls.append(url)
            
    except Exception as e:
        print(f"Upload Error: {e}") # Olhe seu terminal para ver o erro real se persistir
        raise HTTPException(500, f"Falha interna no upload: {str(e)}")

    # 4. Atualização do Banco de Dados
    if new_urls:
        cover_list.extend(new_urls)
        final_cover_str = ";".join(cover_list)

        await db.execute(
            text("UPDATE restaurants SET cover_image_url = :url WHERE id = :rid"),
            {"url": final_cover_str, "rid": restaurant_id}
        )
        await db.commit()

    return {"status": "success", "cover_urls": new_urls}
# ---------------------------
# REFACTORED FEATURES LOGIC
# ---------------------------

@router.get("/features/taxonomy")
async def get_features_taxonomy(
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Returns available taxonomy (groups and features).
    This endpoint is agnostic to specific group codes.
    """
    # 1. Fetch Groups
    groups = (await db.execute(text("SELECT id, code, name, max_select FROM feature_groups ORDER BY id"))).mappings().all()

    # 2. Fetch Active Features
    features = (await db.execute(text("SELECT id, group_id, slug, name FROM features WHERE is_active = true ORDER BY group_id, name"))).mappings().all()

    # 3. Build Tree in Memory
    features_by_group = {}
    for f in features:
        features_by_group.setdefault(f['group_id'], []).append({
            "id": f['id'],
            "slug": f['slug'],
            "name": f['name']
        })

    # 4. Construct Response
    response_data = []
    for g in groups:
        response_data.append({
            "id": g['id'],
            "code": g['code'],
            "name": g['name'],
            "max_select": g['max_select'],
            "items": features_by_group.get(g['id'], [])
        })

    return response_data


@router.get("/{restaurant_id}/features", response_model=RestaurantFeaturesResponse)
async def get_restaurant_features(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> RestaurantFeaturesResponse:
    _require_can_manage_restaurant(staff, restaurant_id)

    # Fetch existing selections joined with group codes
    rows = (await db.execute(text("""
        SELECT fg.code, rf.feature_id
        FROM restaurant_features rf
        JOIN features f ON f.id = rf.feature_id
        JOIN feature_groups fg ON fg.id = f.group_id
        WHERE rf.restaurant_id = :rid
        ORDER BY fg.code, rf.feature_id
    """), {"rid": restaurant_id})).mappings().all()

    # Organize by group code dynamically
    selections: Dict[str, List[int]] = {}
    for r in rows:
        code = str(r["code"])
        fid = int(r["feature_id"])
        selections.setdefault(code, []).append(fid)

    return RestaurantFeaturesResponse(restaurant_id=restaurant_id, selections=selections)


@router.put("/{restaurant_id}/features", response_model=RestaurantFeaturesResponse)
async def update_restaurant_features(
    restaurant_id: int,
    payload: RestaurantFeaturesUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Updates features using a Delta strategy.
    """
    _require_admin_role(staff)
    _require_can_manage_restaurant(staff, restaurant_id)

    # 1. Flatten IDs (mantido igual)
    incoming_feature_ids: Set[int] = set()
    if payload.selections:
        for ids in payload.selections.values():
            if ids:
                incoming_feature_ids.update(ids)
    
    # Handle Empty Update (Clear All)
    if not incoming_feature_ids:
        await db.execute(text("DELETE FROM restaurant_features WHERE restaurant_id = :rid"), {"rid": restaurant_id})
        await db.commit()
        return RestaurantFeaturesResponse(restaurant_id=restaurant_id, selections={})

    # 2. Dynamic Validation (mantido igual - ISSO AQUI ABRE A TRANSAÇÃO IMPLÍCITA)
    validation_query = text("""
        SELECT f.id as feature_id, fg.code as group_code, fg.max_select
        FROM features f
        JOIN feature_groups fg ON f.group_id = fg.id
        WHERE f.id = ANY(:ids) AND f.is_active = true
    """)
    
    valid_features_rows = (await db.execute(validation_query, {"ids": list(incoming_feature_ids)})).mappings().all()

    # ... (Lógica de validação de IDs e Limites mantida igual) ...
    found_ids = {row['feature_id'] for row in valid_features_rows}
    if len(found_ids) != len(incoming_feature_ids):
        invalid_ids = incoming_feature_ids - found_ids
        raise HTTPException(status_code=400, detail=f"Invalid or inactive feature IDs: {invalid_ids}")

    limits_by_group = {} 
    for row in valid_features_rows:
        if row['group_code'] not in limits_by_group:
            limits_by_group[row['group_code']] = row['max_select']

    for group_code, ids_list in payload.selections.items():
        if not ids_list: continue
        limit = limits_by_group.get(group_code)
        if limit is not None and len(ids_list) > limit:
             raise HTTPException(
                status_code=400, 
                detail=f"Too many selections for group '{group_code}'. Max allowed: {limit}"
            )

    # 3. Delta Update Strategy
    try:
        # 3.1 Fetch what currently exists
        current_rows = (await db.execute(
            text("SELECT feature_id FROM restaurant_features WHERE restaurant_id = :rid"),
            {"rid": restaurant_id}
        )).scalars().all()
        current_ids = set(current_rows)

        # 3.2 Calculate Delta
        ids_to_insert = list(incoming_feature_ids - current_ids)
        ids_to_delete = list(current_ids - incoming_feature_ids)

        # 3.3 Apply Changes
        if ids_to_delete:
            await db.execute(
                text("DELETE FROM restaurant_features WHERE restaurant_id = :rid AND feature_id = ANY(:ids)"),
                {"rid": restaurant_id, "ids": ids_to_delete}
            )
        
        if ids_to_insert:
            # INSERT EM LOTE (Fix do erro de sintaxe)
            await db.execute(
                text("INSERT INTO restaurant_features (restaurant_id, feature_id) VALUES (:rid, :fid)"),
                [{"rid": restaurant_id, "fid": fid} for fid in ids_to_insert]
            )

        # 3.4 COMMIT FINAL
        await db.commit()

    except Exception as e:
        await db.rollback()
        raise e

    # 4. Return updated state
    return RestaurantFeaturesResponse(
        restaurant_id=restaurant_id, 
        selections=payload.selections
    )
@router.patch("/status", response_model=RestaurantStatusUpdate)
async def update_restaurant_status(
    payload: RestaurantStatusUpdate,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Endpoint rápido para alternar status Aberto/Fechado e Horas.
    """
    # 1. Busca o restaurante (Query ORM)
    rid = int(staff.get("restaurant_id") or 0)
    stmt = select(Restaurant).where(Restaurant.id == rid)
    result = await db.execute(stmt)
    
    # --- CORREÇÃO AQUI ---
    # Usamos .scalars().first() para pegar a instância do Objeto (Model),
    # permitindo edição. Se usar apenas .first() ou .mappings(), vem como leitura.
    restaurant = result.scalars().first() 
    # ---------------------

    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    # 2. Verifica permissão
    # _require_admin_role(staff) # Descomente se sua lógica exigir admin

    # 3. Atualiza os campos (Agora funciona pois 'restaurant' é um objeto mutável)
    if payload.is_open is not None:
        restaurant.is_open = payload.is_open
    
    if payload.working_hours is not None:
        restaurant.working_hours = payload.working_hours

    # 4. Salva no banco
    await db.commit()
    await db.refresh(restaurant)
    
    return restaurant