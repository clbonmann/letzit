from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict
from jose import jwt
from passlib.context import CryptContext
from app.settings import settings

# Configuração do Bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica se a senha em texto puro bate com o hash salvo.
    """
    # Proteção contra o erro de 72 bytes:
    # Se a senha digitada for absurdamente longa, ela não é a correta de qualquer jeito.
    if len(plain_password.encode('utf-8')) > 72:
        return False
        
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """
    Gera o hash da senha.
    """
    return pwd_context.hash(password)

def create_access_token(
    subject: str | Any, 
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[Dict[str, Any]] = None # <--- Adicionado aqui
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRES_MIN)
    
    # 1. Cria o payload básico
    to_encode = {"exp": expire, "sub": str(subject)}

    # 2. Se tiver dados extras (role, restaurant_id), adiciona no dicionário
    if extra_claims:
        to_encode.update(extra_claims)

    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALG)
    return encoded_jwt