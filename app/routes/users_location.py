from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel

# Tenta importar do deps.py. 
# Se seu arquivo tiver outro nome (ex: dependencies), AJUSTE AQUI.
try:
    from app.deps import get_current_user_id
except ImportError:
    # Fallback caso o arquivo se chame dependencies
    from app.deps_user import get_current_user_id

from app.db import get_db_session # Verifique se esse import bate com seu projeto

router = APIRouter()

# Schema definido aqui para evitar erro de "Module not found"
class LocationUpdateSchema(BaseModel):
    latitude: float
    longitude: float

@router.put("/location")
async def update_location(
    location_data: LocationUpdateSchema,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session)
):
    # Debug no Log do Railway
    print(f"Update location for User ID: {user_id}")
await db.execute(
        text("""
            UPDATE users 
            SET 
                geog = ST_SetSRID(ST_MakePoint(:long, :lat), 4326)::geography, 
                last_loc_at = NOW()
            WHERE id = :uid
        """),
        {
            "lat": location_data.latitude,   # Y
            "long": location_data.longitude, # X (PostGIS pede Longitude primeiro)
            "uid": user_id
        }
    )
    await db.commit()
    
    return {"message": "Location updated", "user_id": user_id}
