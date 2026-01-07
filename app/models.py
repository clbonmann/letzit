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

    email = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # admin | cashier
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    restaurant = relationship("Restaurant", back_populates="staff")

    __table_args__ = (
        UniqueConstraint("restaurant_id", "email", name="uq_restaurant_email"),
        CheckConstraint(
            "role IN ('admin','cashier')",
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
    description = Column(Text, nullable=True)

    start_at = Column(DateTime(timezone=True), server_default=func.now())
    end_at = Column(DateTime(timezone=True), nullable=False)

    status = Column(
        String,
        nullable=False,
        default="ACTIVE",
    )

    accept_limit = Column(Integer, nullable=False)
    accepted_count = Column(Integer, nullable=False, default=0)

    target_batch_size = Column(Integer, nullable=False, default=50)
    max_target_total = Column(Integer, nullable=False, default=300)
    released_total = Column(Integer, nullable=False, default=0)

    accept_ttl_hours = Column(Integer, nullable=False, default=6)
    cancel_grace_min = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    restaurant = relationship("Restaurant", back_populates="offers")
    targets = relationship("OfferTarget", back_populates="offer")
    claims = relationship("OfferClaim", back_populates="offer")

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','PAUSED','CLOSED','EXPIRED')",
            name="ck_offer_status",
        ),
    )


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

    batch_no = Column(Integer, nullable=False)
    state = Column(String, nullable=False, default="RELEASED")

    released_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_at = Column(DateTime(timezone=True), nullable=True)

    offer = relationship("Offer", back_populates="targets")

    __table_args__ = (
        CheckConstraint(
            "state IN ('RELEASED','SENT')",
            name="ck_offer_target_state",
        ),
    )


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
    penalty_applied_at = Column(DateTime(timezone=True), nullable=True)

    offer = relationship("Offer", back_populates="claims")
    user = relationship("User", back_populates="claims")

    __table_args__ = (
        UniqueConstraint("offer_id", "user_id", name="uq_offer_user"),
        CheckConstraint(
            "status IN ('ACCEPTED','REDEEMED','CANCELED','NO_SHOW')",
            name="ck_offer_claim_status",
        ),
    )
