"""changing restaurant to store

Revision ID: 67177f1b59ac
Revises: 36eeb7d35d73
Create Date: 2026-01-29 17:33:33.856504

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import geoalchemy2

# revision identifiers, used by Alembic.
revision: str = '67177f1b59ac'
down_revision: Union[str, None] = '36eeb7d35d73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # --- ENUMS ---
    # Criação do tipo ENUM para OfferType, se ainda não existir
    offer_type_enum = postgresql.ENUM('DISCOUNT_OVER_BILL', 'PRODUCT_DISCOUNT', 'FREE_PRODUCT', 'TABLE_GUARANTEE', 'GIFT', '2GO_DISCOUNT', '2GO_FREE_PRODUCT', 'SPECIAL_PRICE_PRODUCT', name='offertype')
    offer_type_enum.create(op.get_bind(), checkfirst=True)

    # --- TABELAS INDEPENDENTES ---


  
    # stores
    op.create_table('stores',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('cnpj', sa.String(), nullable=True),
        sa.Column('city_slug', sa.String(), nullable=True),
        sa.Column('address_street', sa.String(), nullable=True),
        sa.Column('address_number', sa.String(), nullable=True),
        sa.Column('address_district', sa.String(), nullable=True),
        sa.Column('address_city', sa.String(), nullable=True),
        sa.Column('address_state', sa.String(), nullable=True),
        sa.Column('address_zip', sa.String(), nullable=True),
        sa.Column('address_country', sa.String(), nullable=True),
        sa.Column('logo_url', sa.String(), nullable=True),
        sa.Column('cover_image_url', sa.String(), nullable=True),
        sa.Column('logo_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_open', sa.Boolean(), nullable=False),
        sa.Column('working_hours', sa.BigInteger(), nullable=True),
        sa.Column('geog', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, from_text='ST_GeogFromText', name='geography'), nullable=True),
        sa.Column('balance_km', sa.Integer(), nullable=False),
        sa.Column('balance_home', sa.Integer(), nullable=False),
        sa.Column('reputation', sa.Float(), nullable=True),
        sa.Column('instagram', sa.String(), nullable=True),
        sa.Column('facebook', sa.String(), nullable=True),
        sa.Column('tiktok', sa.String(), nullable=True),
        sa.Column('tripadvisor', sa.String(), nullable=True),
        sa.Column('site', sa.String(), nullable=True),
        sa.Column('whatsapp', sa.String(), nullable=True),
        sa.Column('Store_type_id', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_stores_geog', 'stores', ['geog'], unique=False, postgresql_using='gist')

    
   # store_staff
    op.create_table('store_staff',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('store_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('activation_token', sa.String(), nullable=True),
        sa.Column('activation_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store_id', 'email', name='uq_store_email')
    )
    # Restrição de check para role
    op.create_check_constraint(
        'ck_store_staff_role',
        'store_staff',
        "role IN ('INTERNAL_ADMIN','REST_ADMIN','REST_STAFF')"
    )

    # store_account
    op.create_table('store_account',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.BigInteger(), nullable=False), # Alterado para BigInteger para compatibilidade com stores.id
        sa.Column('credit', sa.Float(), nullable=True),
        sa.Column('debit', sa.Float(), nullable=True),
        sa.Column('balance_km', sa.Float(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('cost_km_cents', sa.Integer(), nullable=True),
        sa.Column('cost_package_cents', sa.Integer(), nullable=True),
        sa.Column('balance_cents', sa.Integer(), nullable=True),
        sa.Column('package_code', sa.String(), nullable=True),
        sa.Column('offer_id', sa.Integer(), nullable=True),
        sa.Column('date_of_bte', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('is_current', sa.Boolean(), nullable=True),
        sa.Column('is_canceled', sa.Boolean(), nullable=True),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_reversed', sa.Boolean(), nullable=True),
        sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_store_account_id'), 'store_account', ['id'], unique=False)

    # offers
    op.create_table('offers_store',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('store_id', sa.BigInteger(), nullable=False),
        sa.Column('staff_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('message', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price_cents', sa.Integer(), nullable=False),
        sa.Column('original_price_cents', sa.Integer(), nullable=True),
        sa.Column('placement', sa.String(), nullable=False),
        sa.Column('radius_km', sa.Integer(), nullable=True),
        sa.Column('start_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('status_reason', sa.String(), nullable=True),
        sa.Column('status_changed_by_staff_id', sa.BigInteger(), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accept_limit', sa.Integer(), nullable=False),
        sa.Column('accepted_count', sa.Integer(), nullable=False),
        sa.Column('claimed_count', sa.Integer(), nullable=False),
        sa.Column('target_batch_size', sa.Integer(), nullable=False),
        sa.Column('max_target_total', sa.Integer(), nullable=False),
        sa.Column('released_total', sa.Integer(), nullable=False),
        sa.Column('accept_ttl_hours', sa.Integer(), nullable=False),
        sa.Column('cancel_grace_min', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('audience_estimate', sa.Integer(), nullable=True),
        sa.Column('offer_type', sa.String(), nullable=False),
        sa.Column('payment_method', sa.String(), nullable=True),
        sa.Column('cost_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('geog', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, from_text='ST_GeogFromText', name='geography'), nullable=True),
        sa.Column('offer_image_url', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # store_features
    op.create_table('store_features',
        sa.Column('store_id', sa.BigInteger(), nullable=False),
        sa.Column('feature_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['feature_id'], ['features.id'], ),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('store_id', 'feature_id')
    )
