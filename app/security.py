from datetime import datetime, timedelta, timezone
from typing import Any, Union, Optional
from jose import jwt
from passlib.context import CryptContext
from app.settings import settings

# Configuração do Hashing de Senha
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# Note: O erro no seu log procurava por 'hash_password', então mantive esse nome
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None, extra_claims: dict = {}) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        # Tenta usar ACCESS_TOKEN_EXPIRE_MINUTES, se não tiver usa padrão 60
        minutes = getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60)
        expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    
    to_encode = {"exp": expire, "sub": str(subject)}
    
    # Injeta roles e rid se existirem
    if extra_claims:
        to_encode.update(extra_claims)
    
    # CORREÇÃO DA LINHA QUEBRADA:
    # Usa settings.JWT_SECRET (ou SECRET_KEY) e o algoritmo definido
    algorithm = getattr(settings, "JWT_ALG", "HS256")
    secret = getattr(settings, "JWT_SECRET", settings.SECRET_KEY)
    
    encoded_jwt = jwt.encode(to_encode, secret, algorithm=algorithm)
    
    return encoded_jwt
