from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
# Certifique-se que estes utilitários existem no seu projeto:
from app.utils.cnpj import normalize_cnpj 
from app.services.storage import upload_image 
# IMPORTANDO SCHEMAS (Agora do lugar certo)
from app.schemas.staff import RestaurantRead, RestaurantUpdate

router = APIRouter(prefix="/staff/restaurant", tags=["staff-restaurant"])

@router.get("", response_model=List[RestaurantRead])
async def list_my_restaurants(
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Lista dados do restaurante.
    - INTERNAL_ADMIN: Vê todos.
    - Staff Normal: Vê apenas o seu.
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
    Atualiza dados textuais (Nome, Endereço, CNPJ).
    """
    role = str(staff.get("role") or "")
    
    # Define ID alvo
    if role == "INTERNAL_ADMIN":
        if not payload.id:
            raise HTTPException(400, "Admin deve informar o 'id' do restaurante.")
        rid = payload.id
    else:
        rid = int(staff["restaurant_id"])

    # Carrega dados atuais
    cur = (await db.execute(text("SELECT id, cnpj FROM restaurants WHERE id = :rid"), {"rid": rid})).mappings().first()
    if not cur:
        raise HTTPException(404, "Restaurante não encontrado.")

    # Valida CNPJ
    new_cnpj = normalize_cnpj(payload.cnpj) if payload.cnpj is not None else cur["cnpj"]
    if new_cnpj and len(new_cnpj) != 14:
        raise HTTPException(400, "CNPJ deve conter 14 dígitos.")

    # Update
    try:
        row = (await db.execute(
            text("""
                UPDATE restaurants
                SET
                  name = COALESCE(:name, name),
                  cnpj = :cnpj,
                  address_street = COALESCE(:address_street, address_street),
                  address_number = COALESCE(:address_number, address_number),
                  address_district = COALESCE(:address_district, address_district),
                  address_city = COALESCE(:address_city, address_city),
                  address_state = COALESCE(:address_state, address_state),
                  address_zip = COALESCE(:address_zip, address_zip),
                  address_country = COALESCE(:address_country, address_country),
                  logo_url = COALESCE(:logo_url, logo_url),
                  logo_updated_at = CASE WHEN :logo_url IS NOT NULL THEN :now ELSE logo_updated_at END
                WHERE id = :rid
                RETURNING id, name, cnpj, logo_url,
                          NULLIF(COALESCE(city, ''), '') AS city,
                          address_street, address_number, address_district,
                          address_city, address_state, address_zip, address_country,
                          ST_Y(geog::geometry) as lat,
                          ST_X(geog::geometry) as long
            """),
            {
                "rid": rid,
                "name": payload.name,
                "cnpj": new_cnpj,
                "address_street": payload.address_street,
                "address_number": payload.address_number,
                "address_district": payload.address_district,
                "address_city": payload.address_city,
                "address_state": payload.address_state,
                "address_zip": payload.address_zip,
                "address_country": payload.address_country,
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
    """Upload de Logo para Cloudinary + Update no Banco."""
    restaurant_id = int(staff["restaurant_id"])

    try:
        url = upload_image(file, folder=f"restaurants/{restaurant_id}")
    except Exception as e:
        print(f"Upload Error: {e}")
        raise HTTPException(500, "Falha no upload da imagem.")

    await db.execute(
        text("UPDATE restaurants SET logo_url = :url, logo_updated_at = NOW() WHERE id = :rid"),
        {"url": url, "rid": restaurant_id}
    )
    await db.commit()

    return {"status": "success", "logo_url": url}
