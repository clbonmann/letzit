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
    store_id: int

class StaffMeResponse(BaseModel):
    id: int
    store_id: int
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
    store_id: int
    email: str
    name: str | None
    role: str
    is_active: bool
    created_at: datetime

class InviteStaffRequest(BaseModel):
    email: EmailStr
    name: str
    role: str 

class UpdateStaffRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6)
    
# --- RESTAURANT PROFILE ---
class StoreRead(BaseModel):
    id: int
    name: str
    cnpj: str | None = None
    logo_url: Optional[str] = None
    reputation: Optional[float]
    address_street: Optional[str] = None
    address_number: Optional[str] = None
    address_district: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_zip: Optional[str] = None
    address_country: Optional[str] = None
    decription: Optional[str] = None
    phone: Optional[str] = None
    is_open: Optional[bool] = None
    working_hours: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    created_at: Optional[datetime] = None
    logo_updated_at: Optional[datetime] = None
    city_slug: Optional[str] = None
    cover_image_url: Optional[str] = None 
    updated_at: Optional[datetime] = None
    instagram: Optional[str] = None
    facebook: Optional[str] = None
    tiktok: Optional[str] = None
    tripadvisor: Optional[str] = None
    site: Optional[str] = None
    whatsapp: Optional[str] = None

    class Config:
        from_attributes = True

class StoreUpdate(BaseModel):
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
    lat: Optional[float] = None
    lon: Optional[float] = None
    city_slug: Optional[str] = None
    instagram: Optional[str] = None
    facebook: Optional[str] = None
    tiktok: Optional[str] = None
    tripadvisor: Optional[str] = None
    site: Optional[str] = None
    whatsapp: Optional[str] = None

    
# --- OFFERS ---
Placement = Literal["NORMAL", "CITY_HOME"]

class QuoteRequest(BaseModel):
    placement: Placement = "NORMAL"
    radius_km: int | None = Field(default=None, ge=1, le=50)
    max_target_total: int = Field(100, ge=1, le=5000)
    city:  Optional[str] = None
    is_adult: Optional[bool] = None
    is_preferred: Optional[bool] = None
    gender: Optional[Literal["M", "F", "O"]] = None
    min_level: Optional[int] = None
    min_reputation: Optional[int] = None


class QuoteBalances(BaseModel):
    current_ta: int
    projected_ta: int
    current_home: int
    projected_home: int

# 2. Modelo principal de resposta
class QuoteResponse(BaseModel):
    audience_estimate: int
    capped_audience: int
    cost: float
    price_cents: int
    message: str
    
    # Campos que estavam faltando e geravam erro 500
    placement: str
    radius_km: Optional[int] = None  # Optional é vital aqui, pois no CITY_HOME ele pode ser nulo
    
    # O objeto aninhado
    balances: QuoteBalances

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
    offer_image_url: Optional[str] = None

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
    offer_image_urls: Optional[str] = None

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
    offer_image_urls: Optional[str] = None

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
    offer_image_urls: Optional[str] = None

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
    balance_ta: float = 0.0
    conversion_rate_percent: float
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
class StoreFeaturesUpdateRequest(BaseModel):
    # Ex: {"CUISINE_TYPE": [1, 2], "NEW_GROUP": [10]}
    selections: Dict[str, List[int]] 

class StoreFeaturesResponse(BaseModel):
    store_id: int
    # Retorna o que o estabelecimento tem salvo, agrupado por código
    selections: Dict[str, List[int]]

# Add this near TaxItem in app/schemas/staff.py
class TaxGroup(BaseModel):
    id: int
    code: str
    name: str
    max_select: Optional[int] = None
    items: List[TaxItem]

class StoreFeaturesUpdateResponse(BaseModel):
    status: str
    store_id: int
    selections: Dict[str, List[int]]

 
class StoreStatusUpdate(BaseModel):
    is_open: Optional[bool] = None
    working_hours: Optional[int] = Field(None, ge=1, le=24)

class AccountHistoryResponse(BaseModel):
    id: int
    credit: float
    debit: float
    balance_ta: float
    package_code: Optional[str] = None
    offer_id: Optional[int] = None
    date_of_bte: datetime
    description: str # Vamos computar isso na hora de exibir (ex: "Compra de Pacote" ou "Oferta #123")

    class Config:
        from_attributes = True

class BalanceResponse(BaseModel):
    balance_ta: float
    last_update: datetime

class BuyPackageRequest(BaseModel):
    package_code: str # Ex: "PKG_STARTER"

class PackageResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    targets: float
    price: float
    features: List[str]
    is_popular: bool
    color_theme: str
    icon_url: Optional[str] = None

    class Config:
        from_attributes = True

# Para criar um pacote novo (Admin Interno)
class PackageCreate(BaseModel):
    code: str
    name: str
    description: str
    targets: float
    price: float
    features: List[str]
    is_popular: bool = False
    color_theme: str = "slate"
    icon_url: Optional[str] = None

# 1. Financeiro (Já tínhamos)
class DashboardFinanceStats(BaseModel):
    balance_ta: int = 0
    avg_cost_per_ta: float
    stock_value_reais: float
    total_credit: int = 0
    total_debit: int = 0
    total_cost: float = 0.0
    total_purchase: float = 0.0
    total_balance: float = 0.0

# 2. Funil de Vendas e Operação (Já tínhamos)
class DashboardFunnelStats(BaseModel):
    today_reached: int
    today_accepted: int
    today_redeemed: int
    today_viewed: int
    today_clicked: int
    today_cancelled: int
    today_conversion_rate: float
    today_cancellation_rate: float


# 3. NOVO: Métricas de Engajamento (Médias dos últimos 30 dias)
class EngagementStats(BaseModel):
    total_reached_count: int     # Clientes alcançados
    total_viewed_count: int      # Clientes que viram
    total_clicked_count: int     # Clientes que clicaram
    total_cancelled_count: int   # Clientes que cancelaram
    total_accepted_count: int    # Clientes que aceitaram
    total_no_shows_count: int    # Clientes que deram no-show
    total_conversion_rate: float # Taxa de conversão total
    total_cancellation_rate: float # Taxa de cancelamento total
    avg_distance_km: float       # Distância média do alvo
    best_placement: str | None   # "NORMAL" ou "CITY_HOME"
    best_offer_type: str | None  # Ex: "DISCOUNT_OVER_BILL"
    cost_over_aquistion: float  # Custo médio por cliente alcançado

# 4. NOVO: Ciclo de Tempo (Médias em Minutos)
class TimeCycleStats(BaseModel):
    avg_time_to_view_min: float   # Release -> View
    avg_time_to_accept_min: float # Release -> Accept
    avg_time_to_redeem_min: float # Release -> Redeem (Ciclo completo)

# 5. NOVO: Detalhe de Oferta Ativa
class ActiveOfferDetail(BaseModel):
    offer_id: int
    title: str
    placement: str
    minutes_active: int          # Tempo desde o release
    audience_expected: int       # Estimativa inicial
    reached_count: int           # Targets criados (real)
    accepted_count: int          # Quantos aceitaram
    redeemed_count: int          # Quantos já foram lá
    conversion_percent: float

# --- RESPOSTA FINAL DO DASHBOARD ---
class DashboardStatsResponse(BaseModel):
    finance: DashboardFinanceStats
    funnel: DashboardFunnelStats
    engagement: EngagementStats
    cycle_times: TimeCycleStats
    
    # Lista detalhada das ativas
    active_offers_list: List[ActiveOfferDetail]