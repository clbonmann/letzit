from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from pydantic import BaseModel
from app.deps import get_current_user_id
from app.settings import settings
from app.db import get_db_session

router = APIRouter()

class LocationUpdateSchema(BaseModel):
    latitude: float
    longitude: float

@router.put("/location")
async def update_location(
    location_data: LocationUpdateSchema,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
):
    # Query corrigida (PostGIS + Campos certos)
    await db.execute(
        text("""
            UPDATE users 
            SET 
                geog = ST_SetSRID(ST_MakePoint(:long, :lat), 4326)::geography, 
                last_loc_at = NOW()
            WHERE id = :uid
        """),
        {
            "lat": location_data.latitude,
            "long": location_data.longitude,
            "uid": user_id
        }
    )
    await db.commit()
    
    return {"message": "Location updated", "user_id": user_id}
