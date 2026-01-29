"""create store_types table and seed

Revision ID: 628063d40f37
Revises: 51f025904eff
Create Date: 2026-01-29 17:10:02.179965

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from datetime import datetime
from typing import Union, Sequence

# revision identifiers, used by Alembic.
revision: str = '628063d40f37'
down_revision: Union[str, None] = '51f025904eff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Cria a Tabela
    op.create_table('store_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_store_types_id'), 'store_types', ['id'], unique=False)

    # 2. Define a estrutura temporária para inserção
    store_types_table = table('store_types',
        column('description', sa.String),
        column('created_at', sa.DateTime),
        column('updated_at', sa.DateTime)
    )

    # 3. Insere os Dados Iniciais (Seed)
    op.bulk_insert(store_types_table, [
        {
            'description': 'Restaurante',
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        },
        {
            'description': 'Bar',
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        },
        {
            'description': 'Farmácia',
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
    ])


def downgrade() -> None:
    op.drop_index(op.f('ix_store_types_id'), table_name='store_types')
    op.drop_table('store_types')