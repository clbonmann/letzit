from pydantic import BaseModel, EmailStr
from typing import Optional

class UserLoginRequest(BaseModel):
    # Agora tudo é opcional, mas validaremos que PELO MENOS UM identificador exista
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None # Ex: +5511999999999
    
    name: Optional[str] = "Cliente" # Nome padrão se não vier
    
    google_id: Optional[str] = None
    apple_id: Optional[str] = None
    firebase_uid: Optional[str] = None # ID único do Firebase (serve pra phone ou social)
    
    photo_url: Optional[str] = None
    fcm_token: Optional[str] = None 
    lat: Optional[float] = None
    lon: Optional[float] = None
