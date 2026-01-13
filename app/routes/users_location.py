from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from pydantic import BaseModel
from app.deps import get_current_user_id
from app.settings import settings

router = APIRouter()

# --- CORREÇÃO DA URL DO BANCO ---
# O Railway manda "postgres://", mas o SQLAlchemy async precisa de "postgresql+asyncpg://"
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://") and "asyncpg" not in db_url:
    # Caso venha postgresql:// mas sem o driver async
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Conexão usando a URL corrigida
engine = create_async_engine(db_url, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db_session_local() -> AsyncSession:
    async with async_session() as session:
        yield session
# --------------------------------

class LocationUpdateSchema(BaseModel):
    latitude: float
    longitude: float

@router.put("/location")
async def update_location(
    location_data: LocationUpdateSchema,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session_local)
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
