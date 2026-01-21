from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr
from geopy.geocoders import Nominatim

# Inicializa o geolocator (Defina um user_agent único para seu app)
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

