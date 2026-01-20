from typing import Optional, List, Literal, Dict
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
from enum import Enum

from app.models import OfferType

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

class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6)
    
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
        from_attributes = True

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
    phone: Optional[str] = None
    description: Optional[str] = None
    is_open: Optional[bool] = None
    working_hours: Optional[float] = None

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
    wallet_balance_km: int = 0
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
    offer_type: OfferType = OfferType.DISCOUNT_OVER_BILL
    city: str | None = None
    title: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)
    accept_limit: int = Field(25, ge=1, le=500)
    max_target_total: int = Field(100, ge=1, le=5000)
    original_price_cents: Optional[int] = None
    price_cents: Optional[int] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    active_minutes: Optional[int] = None
    audience_estimate: Optional[int] = None

class CreateOfferResponse(BaseModel):
    offer_id: int
    staff_id: int
    placement: Placement | None = None
    offer_type: OfferType = OfferType.DISCOUNT_OVER_BILL
    radius_km: int | None = Field(default=None, ge=1, le=50)
    title: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)
    accept_limit: int | None = Field(default=None, ge=1, le=500)
    max_target_total: int | None = Field(default=None, ge=1, le=5000)
    accept_ttl_hours: int | None = Field(default=None, ge=1, le=72)
    audience_estimate: Optional[int] = None
    original_price_cents: Optional[int] = None
    price_cents: Optional[int] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    status: str | None = Field(default=None, max_length=80)

class UpdateCreatedOfferRequest(BaseModel):
    offer_id: int
    staff_id: int
    placement: Placement | None = None
    radius_km: int | None = Field(default=None, ge=1, le=50)
    title: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)
    accept_limit: int | None = Field(default=None, ge=1, le=500)
    max_target_total: int | None = Field(default=None, ge=1, le=5000)
    accept_ttl_hours: int | None = Field(default=None, ge=1, le=72)

class UpdateCreatedOfferResponse(BaseModel):
    offer_id: int
    staff_id: int
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
    client_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    redeemed_at: Optional[datetime] = None
    client_name: Optional[str] = None
    offer_title: Optional[str] = None
    price_to_charge: Optional[int] = None

class DebugAcceptRequest(BaseModel):
    client_id: int

class NoShowRequest(BaseModel):
    claim_id: Optional[int] = None
    qr_token: Optional[str] = None

# --- STATS (ADICIONADO) ---
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
    client_count: int
    label: str

class AudienceStatsResponse(BaseModel):
    total_nearby: int
    active_window_minutes: int
    breakdown: List[AudienceBucket]
    computed_at: datetime
class TaxItem(BaseModel):
    id: int
    slug: str
    name: str

# Payload flexível: aceita qualquer string como chave (código do grupo)
class RestaurantFeaturesUpdateRequest(BaseModel):
    # Ex: {"CUISINE_TYPE": [1, 2], "NEW_GROUP": [10]}
    selections: Dict[str, List[int]] 

class RestaurantFeaturesResponse(BaseModel):
    restaurant_id: int
    # Retorna o que o restaurante tem salvo, agrupado por código
    selections: Dict[str, List[int]]

# Add this near TaxItem in app/schemas/staff.py
class TaxGroup(BaseModel):
    id: int
    code: str
    name: str
    max_select: Optional[int] = None
    items: List[TaxItem]

class RestaurantFeaturesUpdateResponse(BaseModel):
    status: str
    restaurant_id: int
    selections: Dict[str, List[int]]

 
class RestaurantStatusUpdate(BaseModel):
    is_open: Optional[bool] = None
    working_hours: Optional[int] = Field(None, ge=1, le=24)