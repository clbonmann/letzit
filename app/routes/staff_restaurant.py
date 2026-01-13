from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.schemas.restaurants import RestaurantUpdateRequest, RestaurantResponse
from app.utils.cnpj import normalize_cnpj

router = APIRouter(prefix="/staff", tags=["staff-restaurant"])

@router.patch("/restaurant", response_model=RestaurantResponse)
async def update_my_restaurant(
    payload: RestaurantUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> RestaurantResponse:
    
    if staff["role"] == 'INTERNAL_ADMIN':
       rid = payload.id 
    else 
       int(staff["restaurant_id"])

    # carregar atual
    cur = (await db.execute(
        text("""
            SELECT id, name, cnpj,
                   address_street, address_number, address_district,
                   address_city, address_state, address_zip, address_country,
                   logo_url
            FROM restaurants
            WHERE id = :rid
        """),
        {"rid": rid},
    )).mappings().first()

    if not cur:
        raise HTTPException(404, "Restaurant not found")

    new_cnpj = normalize_cnpj(payload.cnpj) if payload.cnpj is not None else cur["cnpj"]
    if new_cnpj is not None and new_cnpj != "" and len(new_cnpj) != 14:
        raise HTTPException(400, "cnpj must have 14 digits (only numbers)")

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
                RETURNING id, name, cnpj,
                          address_street, address_number, address_district,
                          address_city, address_state, address_zip, address_country,
                          logo_url
            """),
            {
                "rid": rid,
                "name": payload.name,
                "cnpj": (new_cnpj if new_cnpj not in ("", None) else None),
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

    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "CNPJ already registered")

    return RestaurantResponse(**row)
