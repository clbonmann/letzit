from pydantic import BaseModel
from typing import Optional

class ClientLoginRequest(BaseModel):
    phone: str          # Formato E.164: +5511999998888
    
    # Dados de Geo (Obrigatórios para o app funcionar bem de cara)
    lat: float
    lon: float
    accuracy: Optional[float] = 0.0
    
    # O token do Firebase para Push (CRUCIAL)
    fcm_token: Optional[str] = None
