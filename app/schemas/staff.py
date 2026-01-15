from typing import Optional, List, Dict
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field

# --- AUTH ---
class StaffLoginRequest(BaseModel):
    email: EmailStr
    password: str

class StaffLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff_id: int
    name: str
    role: str
    restaurant_id: int

class ActivateAccountRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=6)

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)

# --- TEAM ---
class StaffUserResponse(BaseModel):
    id: int
    restaurant_id: int
    email: str
    name: str | None
    role: str
    is_active: bool
    created_at: datetime

class InviteStaffRequest(BaseModel):
    email: EmailStr
    name: str
    role: str # MANAGER, WAITER, KITCHEN

class UpdateStaffRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

# --- RESTAURANT PROFILE ---
class RestaurantRead(BaseModel):
    id: int
    name: str
    cnpj: str | None = None
    city: str | None = None
    address_street: str | None = None
    address_number: str | None = None
    address_district: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_zip: str | None = None
    address_country: str | None = None
    logo_url: Optional[str] = None
    lat: Optional[float] = None
    long: Optional[float] = None
    
    class Config:
        orm_mode = True

class RestaurantUpdate(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    cnpj: Optional[str] = None
    address_street: Optional[str] = None
    address_number: Optional[str] = None
    address_district: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_zip: Optional[str] = None
    address_country: Optional[str] = None
    logo_url: Optional[str] = None 

# --- STATS ---
class DashboardStatsResponse(BaseModel):
    total_revenue_cents: int
    today_accepted: int
    today_redeemed: int
    today_no_shows: int
    conversion_rate: float
    active_offers_count: int
    active_offers_breakdown: Dict[str, int]

class AudienceBucket(BaseModel):
    radius_km: int
    user_count: int
    label: str

class AudienceStatsResponse(BaseModel):
    total_nearby: int
    active_window_minutes: int
    breakdown: List[AudienceBucket]
    computed_at: datetime

# --- POS (REDEEM) ---
class RedeemRequest(BaseModel):
    qr_token: UUID

class NoShowRequest(BaseModel):
    claim_id: Optional[int] = None
    qr_token: Optional[str] = None

class RedeemResponse(BaseModel):
    status: str
    offer_id: int
    claim_id: Optional[int] = None
    user_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    redeemed_at: Optional[datetime] = None
    client_name: Optional[str] = None
    offer_title: Optional[str] = None
    price_to_charge: Optional[int] = None
