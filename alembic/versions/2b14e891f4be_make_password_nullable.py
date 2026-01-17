"""make_password_nullable

Revision ID: 2b14e891f4be
Revises: 3cb08780dc0c
Create Date: 2026-01-17 10:39:08.984748

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b14e891f4be'
down_revision: Union[str, None] = '3cb08780dc0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Permite que password_hash seja NULL
    op.alter_column('restaurant_staff', 'password_hash', nullable=True)

def downgrade() -> None:
    # Volta a ser obrigatório (caso desfaça a migração)
    op.alter_column('restaurant_staff', 'password_hash', nullable=False)