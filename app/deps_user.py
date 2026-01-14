from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError

from app.settings import settings

# 1. Configuração do Swagger
# O tokenUrl aponta para onde o Swagger deve tentar logar. 
# Como nosso login é JSON customizado, o botão "Authorize" do Swagger pode reclamar,
# mas isso é necessário para ele saber que deve enviar o header "Authorization: Bearer ..."
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/client/auth/login/manual")

def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    """
    Decodifica o Token JWT do Cliente e retorna o ID do usuário (uid).
    """
    
    # Previne erro se as chaves não estiverem carregadas
    secret = getattr(settings, "JWT_SECRET", settings.SECRET_KEY)
    algorithm = getattr(settings, "JWT_ALG", "HS256")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # 2. Decodifica o Token
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        
        user_id_str: str = payload.get("sub")
        token_type: str = payload.get("type")

        if user_id_str is None:
            raise credentials_exception
            
        # 3. Trava de Segurança: Garante que é um token de CLIENTE
        # Isso impede que um token de Staff tente acessar dados de Cliente e vice-versa.
        if token_type != "client":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Token inválido para esta operação (Tipo incorreto)"
            )
            
        return int(user_id_str)

    except (JWTError, ValidationError, ValueError):
        raise credentials_exception
