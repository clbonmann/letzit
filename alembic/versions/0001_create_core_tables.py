"""create core tables

Revision ID: 0001_create_core_tables
Revises:
Create Date: 2026-01-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0001_create_core_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("phone_e164", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("level", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("reputation", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # user_stats
    op.create_table(
        "user_stats",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("reviews_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("redeemed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("no_show_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_no_show_at", sa.DateTime(timezone=True), nullable=True),
    )

    # restaurants
    op.create_table(
        "restaurants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # restaurant_staff
    op.create_table(
        "restaurant_staff",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.BigInteger(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("restaurant_id", "email", name="uq_restaurant_email"),
        sa.CheckConstraint("role IN ('admin','cashier')", name="ck_restaurant_staff_role"),
    )

    # offers
    op.create_table(
        "offers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.BigInteger(), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("accept_limit", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("target_batch_size", sa.Integer(), nullable=False, server_default=sa.text("50")),
        sa.Column("max_target_total", sa.Integer(), nullable=False, server_default=sa.text("300")),
        sa.Column("released_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("accept_ttl_hours", sa.Integer(), nullable=False, server_default=sa.text("6")),
        sa.Column("cancel_grace_min", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('ACTIVE','PAUSED','CLOSED','EXPIRED')", name="ck_offer_status"),
    )

    # offer_targets
    op.create_table(
        "offer_targets",
        sa.Column("offer_id", sa.BigInteger(), sa.ForeignKey("offers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("batch_no", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default=sa.text("'RELEASED'")),
        sa.Column("released_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('RELEASED','SENT')", name="ck_offer_target_state"),
    )

    # offer_claims
    op.create_table(
        "offer_claims",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("offer_id", sa.BigInteger(), sa.ForeignKey("offers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("qr_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("penalty_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("offer_id", "user_id", name="uq_offer_user"),
        sa.UniqueConstraint("qr_token", name="uq_offer_claim_qr_token"),
        sa.CheckConstraint("status IN ('ACCEPTED','REDEEMED','CANCELED','NO_SHOW')", name="ck_offer_claim_status"),
    )


def downgrade() -> None:
    op.drop_table("offer_claims")
    op.drop_table("offer_targets")
    op.drop_table("offers")
    op.drop_table("restaurant_staff")
    op.drop_table("restaurants")
    op.drop_table("user_stats")
    op.drop_table("users")
