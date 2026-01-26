from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Literal, Dict, Optional, Set

from geopy.geocoders import Nominatim
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2 import WKTElement
import io
from pydantic import BaseModel

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

# --- Helper Models ---
class DeleteImageRequest(BaseModel):
    url: str

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
        SELECT id, name, cnpj, logo_url, reputation, cover_image_url,
               address_street, address_number, address_district,
               address_city, address_state, address_zip, address_country, description, phone, is_open, working_hours,
               ST_Y(geog::geometry) as lat,
               ST_X(geog::geometry) as lon
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
    current_restaurant = (await db.execute(select(Restaurant).where(Restaurant.id == rid))).scalars().first()
    
    if not current_restaurant:
        raise HTTPException(404, "Restaurante não encontrado.")

    # 3. Prepara os dados dinâmicos
    update_data = payload.model_dump(exclude_unset=True)
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
            update_data.pop("cnpj") 

    # B. Tratamento de Geometria (PostGIS)
    if "lat" in update_data and "lon" in update_data:
        lat = update_data.pop("lat", None)
        lon = update_data.pop("lon", None)
        if lat is not None and lon is not None:
            update_data["geog"] = WKTElement(f"POINT({lon} {lat})", srid=4326)
            address_info = get_address_from_coords(lon, lat)
            if address_info:
                update_data["address_city"] = address_info['city']
                update_data["address_state"] = address_info['state'] 
    
    # C. Timestamp da Logo
    if "logo_url" in update_data and update_data["logo_url"]:
        update_data["logo_updated_at"] = datetime.now(timezone.utc)
    
    update_data["updated_at"] = datetime.now(timezone.utc)

    if not update_data:
        return current_restaurant

    try:
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

    # Configuração do Cloudinary (crop: fill)
    transformations = {
        "width": 600, 
        "height": 400, 
        "crop": "fill", 
        "gravity": "center",
        "quality": "auto",
        "fetch_format": "auto"
    }

    new_urls = []

    try:
        # 3. Loop de Upload
        for file in files:
            # CORREÇÃO: Reseta ponteiro e 'hackeia' o content_type no objeto file
            await file.seek(0)
            file_object = file.file
            # Adiciona atributo content_type ao SpooledTemporaryFile
            setattr(file_object, "content_type", file.content_type)
            
            # Passa o file_object que agora é síncrono E tem content_type
            url = upload_image(
                file_object, 
                folder=f"restaurants/{restaurant_id}/cover",
                transformation=transformations 
            )
            new_urls.append(url)
            
    except Exception as e:
        print(f"Upload Error: {e}")
        raise HTTPException(500, f"Falha no upload: {str(e)}")

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

@router.delete("/cover")
async def delete_restaurant_cover(
    payload: DeleteImageRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    """Remove uma URL específica da lista de capas."""
    restaurant_id = int(staff["restaurant_id"])
    url_to_remove = payload.url

    # 1. Pega a lista atual
    query_select = text("SELECT cover_image_url FROM restaurants WHERE id = :rid")
    res = await db.execute(query_select, {"rid": restaurant_id})
    current_str = res.scalar()

    if not current_str:
        raise HTTPException(404, "Nenhuma imagem encontrada.")

    # 2. Filtra a lista
    current_list = [c for c in current_str.split(";") if c.strip()]
    
    if url_to_remove not in current_list:
        raise HTTPException(404, "Imagem não encontrada na lista deste restaurante.")

    # Remove a URL
    new_list = [url for url in current_list if url != url_to_remove]
    new_str = ";".join(new_list)

    # 3. Atualiza o Banco
    await db.execute(
        text("UPDATE restaurants SET cover_image_url = :url WHERE id = :rid"),
        {"url": new_str, "rid": restaurant_id}
    )
    await db.commit()

    return {"status": "deleted", "remaining_urls": new_list}

# ---------------------------
# FEATURES LOGIC
# ---------------------------

@router.get("/features/taxonomy")
async def get_features_taxonomy(
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Returns available taxonomy (groups and features).
    """
    groups = (await db.execute(text("SELECT id, code, name, max_select FROM feature_groups ORDER BY id"))).mappings().all()
    features = (await db.execute(text("SELECT id, group_id, slug, name FROM features WHERE is_active = true ORDER BY group_id, name"))).mappings().all()

    features_by_group = {}
    for f in features:
        features_by_group.setdefault(f['group_id'], []).append({
            "id": f['id'],
            "slug": f['slug'],
            "name": f['name']
        })

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

    rows = (await db.execute(text("""
        SELECT fg.code, rf.feature_id
        FROM restaurant_features rf
        JOIN features f ON f.id = rf.feature_id
        JOIN feature_groups fg ON fg.id = f.group_id
        WHERE rf.restaurant_id = :rid
        ORDER BY fg.code, rf.feature_id
    """), {"rid": restaurant_id})).mappings().all()

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
    _require_admin_role(staff)
    _require_can_manage_restaurant(staff, restaurant_id)

    incoming_feature_ids: Set[int] = set()
    if payload.selections:
        for ids in payload.selections.values():
            if ids:
                incoming_feature_ids.update(ids)
    
    if not incoming_feature_ids:
        await db.execute(text("DELETE FROM restaurant_features WHERE restaurant_id = :rid"), {"rid": restaurant_id})
        await db.commit()
        return RestaurantFeaturesResponse(restaurant_id=restaurant_id, selections={})

    validation_query = text("""
        SELECT f.id as feature_id, fg.code as group_code, fg.max_select
        FROM features f
        JOIN feature_groups fg ON f.group_id = fg.id
        WHERE f.id = ANY(:ids) AND f.is_active = true
    """)
    
    valid_features_rows = (await db.execute(validation_query, {"ids": list(incoming_feature_ids)})).mappings().all()

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

    try:
        current_rows = (await db.execute(
            text("SELECT feature_id FROM restaurant_features WHERE restaurant_id = :rid"),
            {"rid": restaurant_id}
        )).scalars().all()
        current_ids = set(current_rows)

        ids_to_insert = list(incoming_feature_ids - current_ids)
        ids_to_delete = list(current_ids - incoming_feature_ids)

        if ids_to_delete:
            await db.execute(
                text("DELETE FROM restaurant_features WHERE restaurant_id = :rid AND feature_id = ANY(:ids)"),
                {"rid": restaurant_id, "ids": ids_to_delete}
            )
        
        if ids_to_insert:
            await db.execute(
                text("INSERT INTO restaurant_features (restaurant_id, feature_id) VALUES (:rid, :fid)"),
                [{"rid": restaurant_id, "fid": fid} for fid in ids_to_insert]
            )

        await db.commit()

    except Exception as e:
        await db.rollback()
        raise e

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
    rid = int(staff.get("restaurant_id") or 0)
    stmt = select(Restaurant).where(Restaurant.id == rid)
    result = await db.execute(stmt)
    
    restaurant = result.scalars().first() 

    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    if payload.is_open is not None:
        restaurant.is_open = payload.is_open
    
    if payload.working_hours is not None:
        restaurant.working_hours = payload.working_hours

    await db.commit()
    await db.refresh(restaurant)
    
    return restaurant