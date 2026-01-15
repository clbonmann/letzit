from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr

# --- AUTH ---
class ClientLoginRequest(BaseModel):
    phone: str          # Formato E.164: +5511999998888
    lat: float
    lon: float
    accuracy: Optional[float] = 0.0
    fcm_token: Optional[str] = None

class ClientLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    reputation: float

# --- PROFILE ---
class UserProfileResponse(BaseModel):
    id: int
    name: str | None
    phone: str
    email: str | None
    avatar_url: str | None
    reputation: float
    level: int
    created_at: datetime

class UserUpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    avatar_url: Optional[str] = None

# --- LOCATION ---
class LocationUpdateRequest(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = 0.0

# --- FEED / OFFERS ---
class OfferFeedItem(BaseModel):
    id: int
    restaurant_id: int
    restaurant_name: str
    logo_url: Optional[str]
    title: str
    message: Optional[str]
    price_cents: int
    original_price_cents: Optional[int]
    end_at: str # ou datetime
    distance_m: Optional[int]
    placement: str # 'NORMAL' ou 'CITY_HOME'

class AcceptOfferResponse(BaseModel):
    status: str
    offer_id: int
    user_id: int | None = None
    expires_at: datetime | None = None
    qr_token: str | None = None
    accepted_count: int | None = None
    accept_limit: int | None = None
