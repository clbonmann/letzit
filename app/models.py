from datetime import datetime
import uuid
from geoalchemy2 import Geography

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func
from enum import Enum

class Base(DeclarativeBase):
    pass

# =========================
# OFFER TYPE (OFFER)
# =========================
class OfferType(str, Enum):
    DISCOUNT_OVER_BILL = "DISCOUNT_OVER_BILL"   # Desconto na conta final
    PRODUCT_DISCOUNT = "PRODUCT_DISCOUNT"       # Desconto num prato específico
    FREE_PRODUCT = "FREE_PRODUCT"               # Ganhe uma sobremesa/drink
    TABLE_GUARANTEE = "TABLE_GUARANTEE"         # Reserva garantida (corrigi 'Garantee')
    GIFT = "GIFT"                               # Brinde físico (boné, copo, etc)
    TWO_GO_DISCOUNT = "2GO_DISCOUNT"            # Desconto pra retirar
    TWO_GO_FREE_PRODUCT = "2GO_FREE_PRODUCT"    # Ganhe algo na retirada


# =========================
# CLIENTS (Antigo Users)
# =========================
class Client(Base):
    __tablename__ = "clients"  # <--- MUDOU DE users PARA clients

    id = Column(BigInteger, primary_key=True)
    phone_e164 = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    level = Column(Integer, nullable=False, default=1)
    reputation = Column(Integer, nullable=False, default=100)
    
    # Push Notification Token
    fcm_token = Column(String, nullable=True) 

    # Geo
    # last_loc_at e loc_accuracy_m são suficientes como metadados por enquanto.
    last_loc_at = Column(DateTime(timezone=True), nullable=True)
    loc_accuracy_m = Column(Integer, nullable=True, default=0)

    # Geo: Ponto geográfico (Latitude/Longitude)
    # srid=4326 é o padrão GPS (WGS 84)
    geog = Column(Geography(geometry_type='POINT', srid=4326), nullable=True)

    cooldown_until = Column(DateTime(timezone=True), nullable=True)
    is_blocked = Column(Boolean, nullable=False, default=False)

    # Relacionamentos atualizados
    stats = relationship("ClientStats", back_populates="client", uselist=False)
    claims = relationship("OfferClaim", back_populates="client")


class ClientStats(Base):
    __tablename__ = "client_stats"  # <--- MUDOU DE user_stats PARA client_stats

    client_id = Column( # <--- MUDOU DE user_id PARA client_id
        BigInteger,
        ForeignKey("clients.id", ondelete="CASCADE"), # <--- FK aponta para clients
        primary_key=True,
    )

    reviews_count = Column(Integer, nullable=False, default=0)
    redeemed_count = Column(Integer, nullable=False, default=0)
    no_show_count = Column(Integer, nullable=False, default=0)
    last_no_show_at = Column(DateTime(timezone=True), nullable=True)

    client = relationship("Client", back_populates="stats")


# =========================
# RESTAURANTS
# =========================
class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(BigInteger, primary_key=True)
    name = Column(String, nullable=False)
    
    # Campos de Endereço e Perfil
    cnpj = Column(String, nullable=True)
    city = Column(String, nullable=True)
    city_slug = Column(String, nullable=True)
    address_street = Column(String, nullable=True)
    address_number = Column(String, nullable=True)
    address_district = Column(String, nullable=True)
    address_city = Column(String, nullable=True)
    address_state = Column(String, nullable=True)
    address_zip = Column(String, nullable=True)
    address_country = Column(String, default="BR")
    
    logo_url = Column(String, nullable=True)
    cover_image_url = Column(String, nullable=True)
    logo_updated_at = Column(DateTime(timezone=True), nullable=True)
    phone = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, nullable=False, default=True)

    offers = relationship("Offer", back_populates="restaurant")
    staff = relationship("RestaurantStaff", back_populates="restaurant")

    # Geo: Ponto geográfico (Latitude/Longitude)
    # srid=4326 é o padrão GPS (WGS 84)
    geog = Column(Geography(geometry_type='POINT', srid=4326), nullable=True)

    # Saldo em conta de KM
    balance_km = Column(Integer, default=0, nullable=False)

class RestaurantStaff(Base):
    __tablename__ = "restaurant_staff"

    id = Column(BigInteger, primary_key=True)
    restaurant_id = Column(
        BigInteger,
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )

    name = Column(String, nullable=True)
    email = Column(String, nullable=False)
    password_hash = Column(String, nullable=True)
    role = Column(String, nullable=False)  # INTERNAL_ADMIN, REST_ADMIN, REST_STAFF
    is_active = Column(Boolean, nullable=False, default=True)
    
    # Ativação
    activation_token = Column(String, nullable=True)
    activation_expires_at = Column(DateTime(timezone=True), nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)

    restaurant = relationship("Restaurant", back_populates="staff")

    __table_args__ = (
        UniqueConstraint("restaurant_id", "email", name="uq_restaurant_email"),
        CheckConstraint(
            "role IN ('INTERNAL_ADMIN','REST_ADMIN','REST_STAFF')",
            name="ck_restaurant_staff_role",
        ),
    )


# =========================
# OFFERS
# =========================
class Offer(Base):
    __tablename__ = "offers"

    id = Column(BigInteger, primary_key=True)
    restaurant_id = Column(
        BigInteger,
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    staff_id = Column(BigInteger, nullable=False)
    title = Column(String, nullable=False)
    message = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    
    # Pricing
    price_cents = Column(Integer, nullable=False, default=0)
    original_price_cents = Column(Integer, nullable=True)
    
    # Targeting
    placement = Column(String, nullable=False, default="NORMAL")
    radius_km = Column(Integer, nullable=True)

    start_at = Column(DateTime(timezone=True), server_default=func.now())
    end_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    status = Column(
        String,
        nullable=False,
        default="CREATED",
    )
    status_reason = Column(String, nullable=True)
    status_changed_by_staff_id = Column(BigInteger, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    accept_limit = Column(Integer, nullable=False)
    accepted_count = Column(Integer, nullable=False, default=0)
    claimed_count = Column(Integer, nullable=False, default=0)

    target_batch_size = Column(Integer, nullable=False, default=50)
    max_target_total = Column(Integer, nullable=False, default=300)
    released_total = Column(Integer, nullable=False, default=0)

    accept_ttl_hours = Column(Integer, nullable=False, default=6)
    cancel_grace_min = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    restaurant = relationship("Restaurant", back_populates="offers")
    targets = relationship("OfferTarget", back_populates="offer")
    claims = relationship("OfferClaim", back_populates="offer")
    audience_estimate = Column(Integer, nullable=True)

    offer_type = Column(String, nullable=False, default="DISCOUNT_OVER_BILL")
    payment_method = Column(String, default="CREDITS") # "CREDITS" ou "PAY_AS_YOU_GO"
    
    # Quanto custou essa oferta (se foi em dinheiro)
    cost_amount = Column(Numeric(10, 2), default=0.00)
    
class OfferTarget(Base):
    __tablename__ = "offer_targets"

    offer_id = Column(
        BigInteger,
        ForeignKey("offers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    client_id = Column( # <--- MUDOU DE user_id PARA client_id
        BigInteger,
        ForeignKey("clients.id", ondelete="CASCADE"), # <--- FK aponta para clients
        primary_key=True,
    )

    batch_no = Column(Integer, nullable=False, default=1)
    state = Column(String, nullable=False, default="RELEASED")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    released_at = Column(DateTime(timezone=True), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)

    offer = relationship("Offer", back_populates="targets")


class OfferClaim(Base):
    __tablename__ = "offer_claims"

    id = Column(BigInteger, primary_key=True)

    offer_id = Column(
        BigInteger,
        ForeignKey("offers.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id = Column( # <--- MUDOU DE user_id PARA client_id
        BigInteger,
        ForeignKey("clients.id", ondelete="CASCADE"), # <--- FK aponta para clients
        nullable=False,
    )

    status = Column(String, nullable=False)

    accepted_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    qr_token = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)

    redeemed_at = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    penalty_applied_at = Column(DateTime(timezone=True), nullable=True)

    offer = relationship("Offer", back_populates="claims")
    client = relationship("Client", back_populates="claims") # <--- Renomeada a prop

    __table_args__ = (
        UniqueConstraint("offer_id", "client_id", name="uq_offer_client"), # <--- Constraint atualizada
        CheckConstraint(
            "status IN ('ACCEPTED','REDEEMED','CANCELLED','NO_SHOW')",
            name="ck_offer_claim_status",
        ),
    )