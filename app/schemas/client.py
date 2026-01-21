from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr

# --- AUTH ---
class RequestCodeRequest(BaseModel):
    phone_e164: str

class ClientLoginRequest(BaseModel):
    phone: str
    lat: float
    lon: float
    fcm_token: Optional[str] = None
    password: str

class LoginRequest(BaseModel):
    phone: str
    password: str

class ValidateCodeRequest(BaseModel):
    phone_e164: str
    code: str
    fcm_token: str
    password: str
    # Adicione lat/lon aqui se quiser salvar a localização de cadastro do cliente
    lat: float | None = 0
    lon: float | None = 0

# --- PROFILE & LOCATION ---
class ClientProfileResponse(BaseModel):
    id: int
    name: str | None
    phone: str
    email: str | None
    avatar_url: str | None
    reputation: float
    level: int
    created_at: datetime

class ClientUpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    avatar_url: Optional[str] = None

class LocationUpdateSchema(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = 0.0

# --- FEED & OFFERS ---
class AcceptOfferResponse(BaseModel):
    status: str
    offer_id: int
    client_id: int | None = None
    expires_at: datetime | None = None
    qr_token: str | None = None
    accepted_count: int | None = None
    accept_limit: int | None = None

