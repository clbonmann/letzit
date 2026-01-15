from typing import Optional, List, Literal, Dict
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
from enum import Enum

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

class StaffMeResponse(BaseModel):
    id: int
    restaurant_id: int
    email: str
    role: str
    name: str | None

class ActivationPreviewResponse(BaseModel):
    status: str = "PENDING"
    email: EmailStr
    name: str | None = None

class ActivateAccountRequest(BaseModel):
    token: UUID
    password: str = Field(..., min_length=6, max_length=100)

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=100)

# --- TEAM (Gestão de Equipe) ---
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

# --- RESTAURANT PROFILE (O que faltava) ---
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
    id: Optional[int] = None # Opcional para Staff, Obrigatório para Admin editar terceiros
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

# --- OFFERS ---
Placement = Literal["NORMAL", "CITY_HOME"]

class QuoteRequest(BaseModel):
    placement: Placement = "NORMAL"
    radius_km: int | None = Field(default=None, ge=1, le=50)
    city: str | None = None
    active_minutes: int = Field(30, ge=1, le=240)

class QuoteResponse(BaseModel):
    placement: Placement
    radius_km: int
    price_cents: int
    audience_estimate: int
    city: str | None = None
    max_slots: int | None = None
    used_slots: int | None = None
    available_slots: int | None = None
    status: str | None = None

class CreateOfferRequest(BaseModel):
    placement: Placement = "NORMAL"
    radius_km: int | None = Field(default=None, ge=1, le=50)
    active_minutes: int = Field(30, ge=1, le=240)
    city: str | None = None
    title: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)
    accept_limit: int = Field(25, ge=1, le=500)
    max_target_total: int = Field(100, ge=1, le=5000)

class CreateOfferResponse(BaseModel):
    offer_id: int
    placement: Placement
    radius_km: int
    price_cents: int
    audience_estimate: int
    city: str | None = None
    slot_status: str | None = None

class UpdateCreatedOfferRequest(BaseModel):
    placement: Placement | None = None
    radius_km: int | None = Field(default=None, ge=1, le=50)
    title: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)
    accept_limit: int | None = Field(default=None, ge=1, le=500)
    max_target_total: int | None = Field(default=None, ge=1, le=5000)
    accept_ttl_hours: int | None = Field(default=None, ge=1, le=72)

class UpdateCreatedOfferResponse(BaseModel):
    offer_id: int
    status: str
    placement: str
    radius_km: int | None = None
    title: str | None = None
    message: str | None = None
    accept_limit: int
    max_target_total: int
    accept_ttl_hours: int | None = None

class CloseOfferRequest(BaseModel):
    reason: str | None = Field(default="MANUAL_CLOSE", max_length=64)

class CloseOfferResponse(BaseModel):
    offer_id: int
    previous_status: str
    status: str
    status_reason: str | None
    closed_at: datetime | None

class RepeatOfferRequest(BaseModel):
    hours_valid: int = Field(12, ge=1, le=72)

class RepeatOfferResponse(BaseModel):
    new_offer_id: int
    from_offer_id: int
    status: str
    created_at: datetime
    end_at: datetime

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

# --- POS (REDEEM & NO SHOW) ---
class RedeemStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    CANCELLED = "CANCELLED"
    ALREADY_REDEEMED = "ALREADY_REDEEMED"
    NOT_ACCEPTED = "NOT_ACCEPTED"
    EXPIRED = "EXPIRED"
    REDEEMED = "REDEEMED"       
    NOT_REDEEMABLE = "NOT_REDEEMABLE" 

class RedeemRequest(BaseModel):
    qr_token: UUID

class RedeemResponse(BaseModel):
    status: RedeemStatus
    offer_id: int
    claim_id: Optional[int] = None
    user_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    redeemed_at: Optional[datetime] = None
    client_name: Optional[str] = None
    offer_title: Optional[str] = None
    price_to_charge: Optional[int] = None

class DebugAcceptRequest(BaseModel):
    user_id: int

class NoShowRequest(BaseModel):
    claim_id: Optional[int] = None
    qr_token: Optional[str] = None

