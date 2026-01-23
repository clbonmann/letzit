from datetime import datetime
import uuid
from geoalchemy2 import Geography
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Date,
    Float,
    SmallInteger,
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
    Table,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func

class Base(DeclarativeBase):
    pass

# =========================
# ENUMS
# =========================
class OfferType(str, Enum):
    DISCOUNT_OVER_BILL = "DISCOUNT_OVER_BILL"
    PRODUCT_DISCOUNT = "PRODUCT_DISCOUNT"
    FREE_PRODUCT = "FREE_PRODUCT"
    TABLE_GUARANTEE = "TABLE_GUARANTEE"
    GIFT = "GIFT"
    TWO_GO_DISCOUNT = "2GO_DISCOUNT"
    TWO_GO_FREE_PRODUCT = "2GO_FREE_PRODUCT"
    SPECIAL_PRICE_PRODUCT = "SPECIAL_PRICE_PRODUCT"

# =========================
# TAXONOMY
# =========================
class FeatureGroup(Base):
    __tablename__ = "feature_groups"

    id = Column(SmallInteger, primary_key=True)
    code = Column(String(40), nullable=False, unique=True)  
    name = Column(String(80), nullable=False)
    max_select = Column(SmallInteger, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    features = relationship("Feature", back_populates="groups")

class Feature(Base):
    __tablename__ = "features"

    id = Column(BigInteger, primary_key=True)
    group_id = Column(SmallInteger, ForeignKey("feature_groups.id"), nullable=False)
    slug = Column(String(80), nullable=False)
    name = Column(String(120), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    groups = relationship("FeatureGroup", back_populates="features")
    res_features = relationship("RestaurantFeature", back_populates="feature")

    __table_args__ = (
        UniqueConstraint("group_id", "slug", name="uq_feature_group_slug"),
    )

class RestaurantFeature(Base):
    __tablename__ = "restaurant_features"

    restaurant_id = Column(BigInteger, ForeignKey("restaurants.id", ondelete="CASCADE"), primary_key=True)
    feature_id = Column(BigInteger, ForeignKey("features.id"), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    restaurant = relationship("Restaurant", back_populates="res_features")
    feature = relationship("Feature", back_populates="res_features")

# =========================
# CLIENTS
# =========================
class Client(Base):
    __tablename__ = "clients"

    id = Column(BigInteger, primary_key=True)
    phone_e164 = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    level = Column(Integer, nullable=False, default=1)
    reputation = Column(Integer, nullable=False, default=100)
    password_hash = Column(String, nullable=True)
    fcm_token = Column(String, nullable=True)
    email = Column(String, nullable=True)
    name = Column(String, nullable=True)
    birth_date = Column(Date, nullable=True)
    avatar_url = Column(String, nullable=True)
    last_loc_at = Column(DateTime(timezone=True), nullable=True)
    loc_accuracy_m = Column(Integer, nullable=True, default=0)
    actual_city = Column(String, nullable=True)
    actual_state = Column(String, nullable=True)
    geog = Column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    cooldown_until = Column(DateTime(timezone=True), nullable=True)
    is_blocked = Column(Boolean, nullable=False, default=False)
    is_deleted = Column(Boolean, nullable=False, default=False)

    stats = relationship("ClientStats", back_populates="client", uselist=False)
    claims = relationship("OfferClaim", back_populates="client")
    reviews = relationship("RestaurantReview", back_populates="client")
    # RELAÇÃO COM MATCHMAKER
    targets = relationship("OfferTarget", back_populates="client")

class ClientStats(Base):
    __tablename__ = "client_stats"

    client_id = Column(BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
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
    description = Column(Text, nullable=True)
    cnpj = Column(String, nullable=True)
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
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, nullable=False, default=True)
    is_open = Column(Boolean, nullable=False, default=True)
    working_hours = Column(BigInteger, nullable=True)
    geog = Column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    balance_km = Column(Integer, default=0, nullable=False)
    reputation = Column(Float, default=0, nullable=True)

    res_features = relationship("RestaurantFeature", back_populates="restaurant", cascade="all, delete-orphan")
    offers = relationship("Offer", back_populates="restaurant")
    staff = relationship("RestaurantStaff", back_populates="restaurant")
    reviews = relationship("RestaurantReview", back_populates="restaurant")

class RestaurantStaff(Base):
    __tablename__ = "restaurant_staff"

    id = Column(BigInteger, primary_key=True)
    restaurant_id = Column(BigInteger, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=True)
    email = Column(String, nullable=False)
    password_hash = Column(String, nullable=True)
    role = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    activation_token = Column(String, nullable=True)
    activation_expires_at = Column(DateTime(timezone=True), nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)

    restaurant = relationship("Restaurant", back_populates="staff")

    __table_args__ = (
        UniqueConstraint("restaurant_id", "email", name="uq_restaurant_email"),
        CheckConstraint("role IN ('INTERNAL_ADMIN','REST_ADMIN','REST_STAFF')", name="ck_restaurant_staff_role"),
    )

# =========================
# OFFERS
# =========================
class Offer(Base):
    __tablename__ = "offers"

    id = Column(BigInteger, primary_key=True)
    restaurant_id = Column(BigInteger, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    staff_id = Column(BigInteger, nullable=False)
    title = Column(String, nullable=False)
    message = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    price_cents = Column(Integer, nullable=False, default=0)
    original_price_cents = Column(Integer, nullable=True)
    placement = Column(String, nullable=False, default="NORMAL")
    radius_km = Column(Integer, nullable=True)
    start_at = Column(DateTime(timezone=True), server_default=func.now())
    end_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, nullable=False, default="CREATED")
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
    audience_estimate = Column(Integer, nullable=True)
    offer_type = Column(String, nullable=False, default="DISCOUNT_OVER_BILL")
    payment_method = Column(String, default="CREDITS")
    cost_amount = Column(Numeric(10, 2), default=0.00)
    geog = Column(Geography(geometry_type="POINT", srid=4326), nullable=True)

    restaurant = relationship("Restaurant", back_populates="offers")
    targets = relationship("OfferTarget", back_populates="offer")
    claims = relationship("OfferClaim", back_populates="offer")

# =========================
# MATCHMAKER / TARGETS
# =========================
class OfferTarget(Base):
    __tablename__ = "offer_targets"

    offer_id = Column(BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), primary_key=True)
    client_id = Column(BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    batch_no = Column(Integer, nullable=False, default=1)
    state = Column(String, nullable=False, default="RELEASED")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    released_at = Column(DateTime(timezone=True), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)

    offer = relationship("Offer", back_populates="targets")
    client = relationship("Client", back_populates="targets")

# =========================
# CLAIMS & REVIEWS
# =========================
class OfferClaim(Base):
    __tablename__ = "offer_claims"

    id = Column(BigInteger, primary_key=True)
    offer_id = Column(BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False)
    accepted_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    qr_token = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    redeemed_at = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    penalty_applied_at = Column(DateTime(timezone=True), nullable=True)

    offer = relationship("Offer", back_populates="claims")
    client = relationship("Client", back_populates="claims")
    reviews = relationship("RestaurantReview", back_populates="claim", uselist=False)

    __table_args__ = (
        UniqueConstraint("offer_id", "client_id", name="uq_offer_client"),
        CheckConstraint("status IN ('ACCEPTED','REDEEMED','CANCELLED','NO_SHOW')", name="ck_offer_claim_status"),
    )

class ClientFirstAccess(Base):
    __tablename__ = "client_first_access"

    id = Column(BigInteger, primary_key=True)
    status = Column(String, nullable=False, server_default="'PENDING'")
    code = Column(String, nullable=False)
    phone_e164 = Column(String, nullable=False)
    accepted_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)   
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class RestaurantReview(Base):
    __tablename__ = "restaurant_reviews"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    client_id = Column(BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    restaurant_id = Column(BigInteger, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    offer_claim_id = Column(BigInteger, ForeignKey("offer_claims.id", ondelete="CASCADE"), nullable=False, unique=True)
    rating_food = Column(Integer, nullable=False)
    rating_drink = Column(Integer, nullable=False)
    rating_environment = Column(Integer, nullable=False)
    average_score = Column(Numeric(3, 1), nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    client = relationship("Client", back_populates="reviews")
    restaurant = relationship("Restaurant", back_populates="reviews")
    claim = relationship("OfferClaim", back_populates="reviews")

    __table_args__ = (
        CheckConstraint('rating_food >= 1 AND rating_food <= 5', name='check_rating_food'),
        CheckConstraint('rating_drink >= 1 AND rating_drink <= 5', name='check_rating_drink'),
        CheckConstraint('rating_environment >= 1 AND rating_environment <= 5', name='check_rating_environment'),
    )