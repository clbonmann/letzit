from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# Importe sua função de segurança que decodifica o token
# (O nome pode variar, verifique onde você definiu oauth2_scheme)
from core.security import get_current_user       # Remova o "app."
from schemas.location import LocationUpdateSchema # Remova o "app."

router = APIRouter()

@router.put("/location") # ou POST, dependendo da sua definição
async def update_user_location(
    location_data: LocationUpdateSchema,
    
    # AQUI ESTÁ A MÁGICA:
    # O FastAPI vai pegar o token do Header, validar e te entregar o objeto user
    current_user = Depends(get_current_user), 
    
    db: AsyncSession = Depends(get_db_session)
):
    # Agora temos certeza de quem é o usuário
    user_id = current_user.id 

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
