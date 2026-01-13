from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from schemas.location import LocationUpdateSchema # Remova o "app."
from app.deps import get_current_user_id

router = APIRouter()

@router.put("/location") # ou POST, dependendo da sua definição
async def update_user_location(
    location_data: LocationUpdateSchema,
    
    user_id: int = Depends(get_current_user_id),

    # Se você estiver atualizando a tabela de usuários diretamente:
    await db.execute(
        text("""
            UPDATE users 
            SET latitude = :lat, longitude = :long, updated_at = NOW()
            WHERE id = :uid
        """),
        {
            "lat": location_data.latitude,
            "long": location_data.longitude,
            "uid": user_id  # <--- Usa o ID do token, não o 1
        }
    )
    
    # OU, se você tem uma tabela separada de localizações (user_locations):
    # Verifique se já existe localização para fazer UPDATE ou INSERT (Upsert)
    
    await db.commit()
    
    return {"message": "Location updated", "user_id": user_id}
