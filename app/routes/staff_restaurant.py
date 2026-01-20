from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Dict, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.utils.cnpj import normalize_cnpj 
from app.services.storage import upload_image 
from app.schemas.staff import (
    RestaurantRead, 
    RestaurantUpdate, 
    RestaurantFeaturesResponse, 
    RestaurantFeaturesUpdateRequest, 
    RestaurantFeaturesUpdateResponse, 
    TaxGroup,
    TaxItem, RestaurantStatusUpdate
)

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
        SELECT id, name, cnpj, logo_url,
               NULLIF(COALESCE(city, ''), '') AS city,
               address_street, address_number, address_district,
               address_city, address_state, address_zip, address_country,
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
    Updates textual data (Name, Address, CNPJ).
    """
    role = str(staff.get("role") or "")
    
    if role == "INTERNAL_ADMIN":
        if not payload.id:
            raise HTTPException(400, "Admin deve informar o 'id' do restaurante.")
        rid = payload.id
    else:
        rid = int(staff["restaurant_id"])

    cur = (await db.execute(text("SELECT id, cnpj FROM restaurants WHERE id = :rid"), {"rid": rid})).mappings().first()
    if not cur:
        raise HTTPException(404, "Restaurante não encontrado.")

    new_cnpj = normalize_cnpj(payload.cnpj) if payload.cnpj is not None else cur["cnpj"]
    if new_cnpj and len(new_cnpj) != 14:
        raise HTTPException(400, "CNPJ deve conter 14 dígitos.")

    try:
        row = (await db.execute(
            text("""
                UPDATE restaurants
                SET
                  name = COALESCE(:name, name),
                  description = COALESCE(:description, description),
                  cnpj = :cnpj,
                  address_street = COALESCE(:address_street, address_street),
                  address_number = COALESCE(:address_number, address_number),
                  address_district = COALESCE(:address_district, address_district),
                  address_city = COALESCE(:address_city, address_city),
                  address_state = COALESCE(:address_state, address_state),
                  address_zip = COALESCE(:address_zip, address_zip),
                  address_country = COALESCE(:address_country, address_country),
                  phone = COALESCE(:phone, phone),
                  logo_url = COALESCE(:logo_url, logo_url),
                  logo_updated_at = CASE WHEN :logo_url IS NOT NULL THEN :now ELSE logo_updated_at END
                WHERE id = :rid
                RETURNING id, name, description, cnpj, logo_url,
                          NULLIF(COALESCE(city, ''), '') AS city,
                          address_street, address_number, address_district,
                          address_city, address_state, address_zip, address_country, phone,
                          ST_Y(geog::geometry) as lat,
                          ST_X(geog::geometry) as long
            """),
            {
                "rid": rid,
                "name": payload.name,
                "description": payload.description,
                "cnpj": new_cnpj,
                "address_street": payload.address_street,
                "address_number": payload.address_number,
                "address_district": payload.address_district,
                "address_city": payload.address_city,
                "address_state": payload.address_state,
                "address_zip": payload.address_zip,
                "address_country": payload.address_country,
                "phone": payload.phone,
                "is_open": payload.is_open,
                "working_hours": payload.working_hours,
                "logo_url": payload.logo_url,
                "now": datetime.now(timezone.utc),
            },
        )).mappings().first()

        await db.commit()
        return RestaurantRead(**row)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "CNPJ já registrado.")


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
    # 1. Busca o restaurante do staff
    restaurant_id = int(staff["restaurant_id"])
    
    restaurant = (await db.execute(
        text("SELECT id, is_open, working_hours FROM restaurants WHERE id = :rid"),
        {"rid": restaurant_id}
    )).mappings().first()
    # 2. Verifica permissão (apenas Admin ou Gerente deveriam abrir/fechar)
    _require_admin_role(staff) 

    # 3. Atualiza apenas os campos enviados
    if payload.is_open is not None:
        restaurant.is_open = payload.is_open
    
    if payload.working_hours is not None:
        restaurant.working_hours = payload.working_hours

    # 4. Salva
    await db.commit()
    await db.refresh(restaurant)
    
    return restaurant