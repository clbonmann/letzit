from datetime import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# =========================
# USERS
# =========================
class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    phone_e164 = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    level = Column(Integer, nullable=False, default=1)
    reputation = Column(Integer, nullable=False, default=100)
    
    # Push Notification Token (Adicionado para suportar o login)
    fcm_token = Column(String, nullable=True) 

    # Geo (Adicionados para suportar PostGIS nas rotas)
    # Nota: Em produção, você precisa garantir que a extensão PostGIS está ativa no banco
    # geog = Column(Geography(geometry_type='POINT', srid=4326), nullable=True)
    # Como não tenho a lib geoalchemy2 aqui, vou deixar comentado ou usar TypeDecorator se necessário.
    # Mas assumindo que você usa raw SQL com ST_SetSRID, o SQLAlchemy ignora se não mapear, 
    # ou podemos mapear como 'UserDefined' ou simplesmente ignorar no ORM se só usarmos SQL bruto.
    # Para simplificar e evitar erro de import da geoalchemy2 se não tiver instalada:
    # last_loc_at e loc_accuracy_m são suficientes como metadados.
    
    last_loc_at = Column(DateTime(timezone=True), nullable=True)
    loc_accuracy_m = Column(Integer, nullable=True, default=0)

    cooldown_until = Column(DateTime(timezone=True), nullable=True)
    is_blocked = Column(Boolean, nullable=False, default=False)

    stats = relationship("UserStats", back_populates="user", uselist=False)
    claims = relationship("OfferClaim", back_populates="user")


class UserStats(Base):
    __tablename__ = "user_stats"

    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    reviews_count = Column(Integer, nullable=False, default=0)
    redeemed_count = Column(Integer, nullable=False, default=0)
    no_show_count = Column(Integer, nullable=False, default=0)
    last_no_show_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="stats")


# =========================
# RESTAURANTS
# =========================
class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(BigInteger, primary_key=True)
    name = Column(String, nullable=False)
    
    # Campos de Endereço e Perfil (Consistência com rotas)
    cnpj = Column(String, nullable=True)
    city = Column(String, nullable=True)
    city_slug = Column(String, nullable=True) # Para a Home
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


class RestaurantStaff(Base):
    __tablename__ = "restaurant_staff"

    id = Column(BigInteger, primary_key=True)
    restaurant_id = Column(
        BigInteger,
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )

    name = Column(String, nullable=True) # Adicionado para bater com schemas
    email = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # INTERNAL_ADMIN, CLIENT_ADMIN, CLIENT_STAFF
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
        # Atualizei a constraint para os roles novos que usamos
        CheckConstraint(
            "role IN ('INTERNAL_ADMIN','CLIENT_ADMIN','CLIENT_STAFF')",
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

    title = Column(String, nullable=False)
    message = Column(String, nullable=True) # Adicionado ("Ei Osvaldo...")
    description = Column(Text, nullable=True)
    
    # Pricing
    price_cents = Column(Integer, nullable=False, default=0)
    original_price_cents = Column(Integer, nullable=True)
    
    # Targeting
    placement = Column(String, nullable=False, default="NORMAL") # NORMAL, CITY_HOME
    radius_km = Column(Integer, nullable=True)

    start_at = Column(DateTime(timezone=True), server_default=func.now())
    end_at = Column(DateTime(timezone=True), nullable=False)

    status = Column(
        String,
        nullable=False,
        default="CREATED", # CREATED, ACTIVE, PAUSED, CLOSED
    )
    status_reason = Column(String, nullable=True)
    status_changed_by_staff_id = Column(BigInteger, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    accept_limit = Column(Integer, nullable=False)
    accepted_count = Column(Integer, nullable=False, default=0)
    claimed_count = Column(Integer, nullable=False, default=0) # Quantos foram na loja

    target_batch_size = Column(Integer, nullable=False, default=50)
    max_target_total = Column(Integer, nullable=False, default=300)
    released_total = Column(Integer, nullable=False, default=0)

    accept_ttl_hours = Column(Integer, nullable=False, default=6)
    cancel_grace_min = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    restaurant = relationship("Restaurant", back_populates="offers")
    targets = relationship("OfferTarget", back_populates="offer")
    claims = relationship("OfferClaim", back_populates="offer")


class OfferTarget(Base):
    __tablename__ = "offer_targets"

    offer_id = Column(
        BigInteger,
        ForeignKey("offers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    batch_no = Column(Integer, nullable=False, default=1)
    state = Column(String, nullable=False, default="RELEASED")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    released_at = Column(DateTime(timezone=True), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True) # Se virou claim

    offer = relationship("Offer", back_populates="targets")


class OfferClaim(Base):
    __tablename__ = "offer_claims"

    id = Column(BigInteger, primary_key=True)

    offer_id = Column(
        BigInteger,
        ForeignKey("offers.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
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
    user = relationship("User", back_populates="claims")

    __table_args__ = (
        UniqueConstraint("offer_id", "user_id", name="uq_offer_user"),
        # Correção aqui: Padronizando CANCELLED
        CheckConstraint(
            "status IN ('ACCEPTED','REDEEMED','CANCELLED','NO_SHOW')",
            name="ck_offer_claim_status",
        ),
    )

