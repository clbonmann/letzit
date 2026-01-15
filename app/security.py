from datetime import datetime, timedelta, timezone
from typing import Any, Union, Optional
from jose import jwt
from passlib.context import CryptContext
from app.settings import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(
    subject: Union[str, Any], 
    expires_delta: Optional[timedelta] = None, 
    extra_claims: dict = {}
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        # Pega o tempo padrão do settings
        minutes = getattr(settings, "JWT_EXPIRES_MIN", 60 * 24)
        expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    
    to_encode = {"exp": expire, "sub": str(subject)}
    
    if extra_claims:
        to_encode.update(extra_claims)
    
    # Garante que temos uma chave secreta
    secret = settings.JWT_SECRET
    if not secret:
        raise ValueError("JWT_SECRET not configured in settings")

    algorithm = settings.JWT_ALG
    
    encoded_jwt = jwt.encode(to_encode, secret, algorithm=algorithm)
    
    return encoded_jwt

