from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.settings import settings

bearer = HTTPBearer(auto_error=False)

async def get_current_staff(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = creds.credentials
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
        staff_id = int(payload.get("sub"))
        
        # Opcional: Validar se token tem role (para evitar token de cliente aqui)
        # if payload.get("role") is None: raise ...
        
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Busca no banco para garantir que staff ainda existe e está ativo
    staff = (await db.execute(
        text("""
            SELECT id, restaurant_id, email, role, is_active, name
            FROM restaurant_staff
            WHERE id = :sid
        """),
        {"sid": staff_id},
    )).mappings().first()

    if not staff or not staff["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Staff inactive or not found")

    return dict(staff)

