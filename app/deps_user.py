# app/deps_user.py
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from app.security import SECRET_KEY, ALGORITHM # Importe das suas configs

# O Base44 deve enviar o token neste formato
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="users/login")

async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Tenta decodificar o token usando sua chave secreta do Railway
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub")
        
        if user_id_str is None:
            raise credentials_exception
            
        return int(user_id_str)
        
    except JWTError:
        raise credentials_exception
