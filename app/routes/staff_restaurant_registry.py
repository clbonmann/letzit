from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff", tags=["staff-restaurant"])


class RestaurantRegistryItem(BaseModel):
    id: int
    name: str
    cnpj: str | None = None
    city: str | None = None
    address_street: str | None = None
    address_number: str | None = None
    address_district: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_zip: str | None = None
    address_country: str | None = None
    logo_url: Optional[str] = None
    lat: Optional[float] = None
    long: Optional[float] = None
    
@router.get("/registry", response_model=list[RestaurantRegistryItem])
async def list_restaurants_registry(
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> list[RestaurantRegistryItem]:
    role = str(staff.get("role") or "")

    if role not in ("INTERNAL_ADMIN", "CLIENT_ADMIN"):
        raise HTTPException(status_code=403, detail="Not allowed")

    if role == "INTERNAL_ADMIN":
        rows = (await db.execute(
            text("""
                SELECT id,
                     name, 
                     NULLIF(COALESCE(city, ''), '') AS city, 
                     cnpj, 
                     address_street, 
                     address_number,
                     address_district,
                     address_city, 
                     address_state, 
                     address_zip, 
                     address_country, 
                     logo_url,
                     ST_Y(geog::geometry) as lat,
                     ST_X(geog::geometry) as long
                FROM restaurants
                ORDER BY id DESC
            """)
        )).mappings().all()
        return [RestaurantRegistryItem(**r) for r in rows]

    # CLIENT_ADMIN: apenas o restaurante do login
    rid = int(staff["restaurant_id"])
    row = (await db.execute(
        text("""
            SELECT   id,
                     name,  
                     NULLIF(COALESCE(city, ''), '') AS city, 
                     cnpj, 
                     address_street, 
                     address_number,
                     address_district,
                     address_city, 
                     address_state, 
                     address_zip, 
                     address_country, 
                     logo_url,
                     ST_Y(geog::geometry) as lat,
                     ST_X(geog::geometry) as long
            FROM restaurants
            WHERE id = :rid
        """),
        {"rid": rid},
    )).mappings().first()

    if not row:
        # caso raro: staff aponta para restaurant inexistente
        raise HTTPException(status_code=404, detail="Restaurant not found")

    return [RestaurantRegistryItem(**row)]
