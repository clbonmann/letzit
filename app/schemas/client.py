from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel, EmailStr
from geopy.geocoders import Nominatim

# Inicializa o geolocator (Defina um user_agent único)
geolocator = Nominatim(user_agent="letzit_delivery_app_v1")

def get_address_from_coords(lat, lon):
    try:
        # Pede ao OpenStreetMap o endereço
        location = geolocator.reverse(f"{lat}, {lon}", language='pt')
        address = location.raw.get('address', {})
        
        # O OpenStreetMap varia os nomes (city, town, village), então tentamos todos
        city = address.get('city') or address.get('town') or address.get('village') or address.get('municipality')
        state = address.get('state')
        state_code = address.get('ISO3166-2-lvl4') # Ex: BR-SC
        
        return {
            "city": city,
            "state": state,
            "full_address": location.address
        }
    except Exception as e:
        print(f"Erro ao geocodificar: {e}")
        return None
    
# --- AUTH ---
class RequestCodeRequest(BaseModel):
    phone: str

class CheckPhoneRequest(BaseModel):
    phone: str

class CompleteRegistrationRequest(BaseModel):
    phone: str
    code: str # Precisamos do código novamente para garantir que validou
    name: str
    birth_date: date
    email: str
    password: str

class ClientLoginRequest(BaseModel):
    phone: str
    password: str
    lat: float = 0.0         
    lon: float = 0.0
    fcm_token: str | None = None

class LoginRequest(BaseModel):
    phone: str
    password: str

class ValidateCodeRequest(BaseModel):
    phone: str
    code: str

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

class ClientUpdateProfileRequest(BaseModel):
    name: str | None
    email: str | None
    birth_date: date | None

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

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    birth_date: Optional[date] = None
    email: Optional[EmailStr] = None
    avatar_url: Optional[str] = None