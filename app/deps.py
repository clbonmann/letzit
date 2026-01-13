from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from app.settings import settings

# Isso diz ao Swagger onde pegar o token se não tiver
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/users/login")

async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    """
    Valida o Token JWT e extrai o ID do usuário.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not settings.JWT_SECRET:
        raise RuntimeError("JWT_SECRET not configured")
    try:
        # 1. Tenta decodificar o token usando a chave secreta
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=settings.JWT_ALG)
        
        # 2. Pega o "subject" (sub) que guardamos lá na criação (geralmente é o ID)
        user_id: str = payload.get("sub")
        
        if user_id is None:
            raise credentials_exception
            
        # 3. Retorna o ID convertido para inteiro
        return int(user_id)
        
    except JWTError:
        # Se o token for inválido ou expirado, cai aqui
        raise credentials_exception
