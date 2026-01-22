from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError

from app.settings import settings

# Login do Cliente
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/client/auth/token")

def get_current_client_id(token: str = Depends(oauth2_scheme)) -> int:
    """
    Decodifica o Token JWT do Cliente e retorna o ID do usuário (uid).
    """
    secret = settings.JWT_SECRET
    if not secret:
        raise RuntimeError("JWT_SECRET is not configured")
        
    algorithm = settings.JWT_ALG

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        
        client_id_str: str = payload.get("sub")
        token_type: str = payload.get("type") # client vs staff

        if client_id_str is None:
            raise credentials_exception
            
        # Garante que é um token de CLIENTE
        if token_type != "client":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Invalid token type (expected client)"
            )
            
        return int(client_id_str)

    except (JWTError, ValidationError, ValueError):
        raise credentials_exception

