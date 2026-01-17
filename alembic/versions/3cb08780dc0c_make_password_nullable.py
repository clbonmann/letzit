"""make_password_nullable

Revision ID: 3cb08780dc0c
Revises: 509478fdcfc7
Create Date: 2026-01-17 10:38:16.722967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cb08780dc0c'
down_revision: Union[str, None] = '509478fdcfc7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Permite que password_hash seja NULL
    op.alter_column('restaurant_staff', 'password_hash', nullable=True)

def downgrade() -> None:
    # Volta a ser obrigatório (caso desfaça a migração)
    op.alter_column('restaurant_staff', 'password_hash', nullable=False)