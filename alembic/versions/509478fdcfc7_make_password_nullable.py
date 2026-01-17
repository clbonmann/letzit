"""make_password_nullable

Revision ID: 509478fdcfc7
Revises: 7c4529ffcfd7
Create Date: 2026-01-17 10:37:25.822729

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '509478fdcfc7'
down_revision: Union[str, None] = '7c4529ffcfd7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass