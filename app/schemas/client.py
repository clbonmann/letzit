from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel, EmailStr

# Se estiver usando geopy, mantenha. Se não, pode remover esse bloco
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="letzit_app_v1")
except ImportError:
    geolocator = None

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
    lat: float | None = 0
    lon: float | None = 0

# --- PROFILE & LOCATION ---
class ClientProfileResponse(BaseModel):
    id: int
    name: str | None
    phone: str
    email: str | None
    birth_date: date | None
    avatar_url: str | None
    reputation: float
    level: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class ClientUpdateProfileRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    birth_date: date | None = None
    avatar_url: str | None = None

class LocationUpdateSchema(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = 0.0

# --- OFFERS ---
class AcceptOfferResponse(BaseModel):
    status: str
    offer_id: int
    client_id: int | None = None
    expires_at: datetime | None = None
    qr_token: str | None = None
    accepted_count: int | None = None
    accept_limit: int | None = None